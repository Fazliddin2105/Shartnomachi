"""Contract approval (spec §5.5): who, when, device/IP, which version, hash."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import get_client
from app.core.crypto import canonical_json, hmac_sha256, sha256_hex
from app.core.errors import AppError, Conflict, Forbidden, ValidationFailed
from app.core.timeutils import ensure_utc, utcnow
from app.integrations import eimzo
from app.modules.anchoring import hooks as anchor_hooks
from app.modules.audit import service as audit
from app.modules.auth import otp as otp_service
from app.modules.auth.models import OtpPurpose
from app.modules.auth.service import mark_identity_verified, pinfl_hash
from app.modules.contracts import service as contracts
from app.modules.contracts.models import (
    ApprovalMethod,
    Contract,
    ContractApproval,
    ContractParty,
    ContractStatus,
    ContractVersion,
)
from app.modules.files import service as files
from app.modules.users.models import Company, User

log = logging.getLogger(__name__)


def _signing_party(c: Contract, user: User) -> ContractParty:
    party = next((p for p in c.parties if p.user_id == user.id and p.role in contracts.SIGNING_ROLES), None)
    if party is None:
        raise Forbidden("Only party A or B can approve the contract", code="not_signing_party")
    return party


def _ready(c: Contract) -> None:
    if c.status != ContractStatus.PENDING_APPROVAL:
        raise Conflict("Contract is not awaiting approval", code="not_pending")


def seal(*, sha256: str, party_id: str, user_id: str, method: str, signed_at: datetime) -> str:
    return hmac_sha256(
        f"{sha256}|{party_id}|{user_id}|{method}|{ensure_utc(signed_at).isoformat()}", purpose="approval"
    )


async def request_otp(db: AsyncSession, c: Contract, user: User) -> otp_service.OtpIssued:
    _ready(c)
    _signing_party(c, user)
    if not user.phone:
        raise ValidationFailed("Your account has no phone number", code="phone_missing")
    v = await contracts.current_version(db, c)
    return await otp_service.issue(db, phone=user.phone, purpose=OtpPurpose.APPROVE_CONTRACT, context_ref=v.id.hex)


async def approve(
    db: AsyncSession,
    c: Contract,
    user: User,
    *,
    method: ApprovalMethod,
    code: str | None,
    pkcs7: str | None,
    expected_sha256: str,
) -> dict[str, Any]:
    _ready(c)
    party = _signing_party(c, user)
    v: ContractVersion = await contracts.current_version(db, c)
    if expected_sha256 != v.sha256:
        # The client must show the exact hash being signed; stale screens are rejected.
        raise Conflict(
            "Document changed since you opened it", code="version_mismatch", details={"current_sha256": v.sha256}
        )
    if await db.scalar(
        select(ContractApproval.id).where(ContractApproval.version_id == v.id, ContractApproval.party_id == party.id)
    ):
        raise Conflict("Already approved", code="already_approved")

    proof: dict[str, Any]
    if method == ApprovalMethod.OTP:
        if not code or not user.phone:
            raise ValidationFailed("OTP code is required", code="otp_required")
        otp = await otp_service.verify(
            db, phone=user.phone, code=code, purpose=OtpPurpose.APPROVE_CONTRACT, context_ref=v.id.hex
        )
        proof = {"otp_id": str(otp.id), "phone_masked": user.phone[:6] + "***" + user.phone[-2:]}
    elif method == ApprovalMethod.EIMZO:
        if not pkcs7:
            raise ValidationFailed("PKCS#7 signature is required", code="pkcs7_required")
        proof = await _verify_eimzo(db, c, v, party, user, pkcs7)
    else:
        raise ValidationFailed("Approval via OneID is not supported yet", code="method_unsupported")

    client = get_client()
    now = utcnow().replace(microsecond=0)
    approval = ContractApproval(
        version_id=v.id,
        party_id=party.id,
        user_id=user.id,
        method=method,
        sha256=v.sha256,
        ip=client.ip,
        device=(client.user_agent or "")[:255] or None,
        signed_at=now,
        proof=proof,
        seal=seal(sha256=v.sha256, party_id=str(party.id), user_id=str(user.id), method=method.value, signed_at=now),
    )
    db.add(approval)
    party.confirmed_at = now
    await db.flush()
    await audit.record(
        db,
        action="contract.approve",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"version": v.number, "sha256": v.sha256, "party": party.role.value, "method": method.value},
    )

    signing = [p for p in c.parties if p.role in contracts.SIGNING_ROLES]
    approved_ids = set(await db.scalars(select(ContractApproval.party_id).where(ContractApproval.version_id == v.id)))
    all_done = bool(signing) and all(p.id in approved_ids for p in signing)
    await contracts.log_event(
        db,
        c,
        actor_id=user.id,
        side=party.role.value,
        kind="signed",
        payload={"version": v.number, "method": method.value},
    )
    if all_done:
        await contracts.activate(db, c)
        await _build_signature_container(db, v, user)
        await anchor_hooks.contract_signed(db, version=v, approvals=await list_for_version(db, v.id))
        from app.modules.contracts import archive

        await archive.archive_signed(db, c, v)
        await contracts.log_event(db, c, actor_id=user.id, side=None, kind="activated", payload={"version": v.number})
        await contracts.notify_parties(
            db,
            c,
            except_user=None,
            event="contract.activated",
            title="Shartnoma kuchga kirdi",
            body=f'"{c.title}" barcha tomonlar tomonidan imzolandi va arxivingizga saqlandi. '
            "Majburiyatlar eslatmalarga qo'shildi.",
        )
    else:
        await contracts.notify_parties(
            db,
            c,
            except_user=user.id,
            event="contract.approved_by_party",
            title="Shartnoma tasdiqlandi",
            body=f'"{c.title}": {party.role.value} tomon tasdiqladi. Sizning tasdig\'ingiz kutilmoqda.',
        )
    return {
        "approved": True,
        "party": party.role.value,
        "contract_status": c.status.value,
        "pending_parties": [p.role.value for p in signing if p.id not in approved_ids],
        "method": method.value,
        "legal_strength": "qualified_signature" if method == ApprovalMethod.EIMZO else "simple_electronic",
        "form_warning": None
        if c.form_requirement.value == "simple"
        else contracts.FORM_WARNING.format(form=contracts._FORM_TITLES[c.form_requirement.value]),
    }


async def list_for_version(db: AsyncSession, version_id: Any) -> list[ContractApproval]:
    return list(
        await db.scalars(
            select(ContractApproval)
            .where(ContractApproval.version_id == version_id)
            .order_by(ContractApproval.signed_at)
        )
    )


# --- E-IMZO -----------------------------------------------------------------------------

SIGNING_DOC_TYPE = "lexlab.contract.approval.v1"


def signing_document(c: Contract, v: ContractVersion) -> bytes:
    """Exactly what every party signs with E-IMZO.

    Party-independent on purpose: all signatures cover the same bytes, so they can be
    joined into one multi-signature PKCS#7 container (``/frontend/pkcs7/join``).
    The content hash binds the signature to the full, immutable version text.
    """
    return canonical_json(
        {
            "type": SIGNING_DOC_TYPE,
            "contract_id": str(c.id),
            "title": c.title,
            "version": v.number,
            "content_sha256": v.sha256,
        }
    )


async def eimzo_payload(db: AsyncSession, c: Contract, user: User) -> dict[str, Any]:
    _ready(c)
    _signing_party(c, user)
    v = await contracts.current_version(db, c)
    doc = signing_document(c, v)
    return {
        "document_b64": base64.b64encode(doc).decode(),
        "document_sha256": sha256_hex(doc),
        "content_sha256": v.sha256,
        "version": v.number,
        "detached": False,
    }


def _mask(value: str | None) -> str | None:
    return f"{value[:3]}*******{value[-4:]}" if value and len(value) > 7 else value


async def _verify_eimzo(
    db: AsyncSession, c: Contract, v: ContractVersion, party: ContractParty, user: User, pkcs7: str
) -> dict[str, Any]:
    settings = get_settings()
    client = eimzo.EimzoClient()
    signed = await client.attach_timestamp(pkcs7) if settings.eimzo_require_timestamp else pkcs7
    result = await client.verify_attached(signed)

    # WHAT was signed: byte-exact match with this contract version
    if result.document != signing_document(c, v):
        raise Forbidden("The signature does not cover this contract version", code="eimzo_document_mismatch")
    if len(result.signers) != 1:
        raise Forbidden("Exactly one signer is expected", code="eimzo_unexpected_signers")
    signer = result.signers[0]
    if settings.eimzo_require_timestamp and not signer.timestamp_verified:
        raise Forbidden("Trusted timestamp is missing or invalid", code="eimzo_timestamp_invalid")
    cert = signer.certificate
    if not cert.pinfl:
        raise Forbidden("Certificate has no PINFL", code="eimzo_no_pinfl")

    # WHO signed: the certificate holder must be this account's (verified) person ...
    h = pinfl_hash(cert.pinfl)
    if user.verified_pinfl_hash is None:
        taken = await db.scalar(select(User.id).where(User.verified_pinfl_hash == h, User.id != user.id))
        if taken:
            raise Forbidden("This E-IMZO key belongs to another account", code="eimzo_signer_mismatch")
        mark_identity_verified(user, pinfl=cert.pinfl, via="eimzo", full_name=cert.common_name, tin=cert.person_tin)
        await audit.record(
            db,
            action="identity.verified",
            entity="user",
            entity_id=user.id,
            actor_id=user.id,
            meta={"via": "eimzo_signature", "cert_serial": cert.serial_number},
        )
    elif user.verified_pinfl_hash != h:
        raise Forbidden("The signer is not the account holder", code="eimzo_signer_mismatch")

    # ... and, when signing on behalf of a company, the key must be that company's (legal TIN).
    if party.company_id is not None:
        company = await db.get(Company, party.company_id)
        if company is None or cert.legal_tin != company.stir:
            raise Forbidden("The key is not issued to this company (STIR mismatch)", code="eimzo_company_mismatch")

    # The PKCS#7 embeds the certificate (personal data) -> encrypted file storage, not a DB column.
    stored = await files.save_bytes(
        db,
        data=base64.b64decode(signed),
        filename=f"contract-v{v.number}-{party.role.value}.p7s",
        declared_mime="application/pkcs7-signature",
        trusted_mime="application/pkcs7-signature",
        owner_id=user.id,
        purpose="signature",
    )
    return {
        "pkcs7_file_id": str(stored.id),
        "pkcs7_sha256": stored.sha256,
        "document_sha256": sha256_hex(result.document or b""),
        "cert_serial": cert.serial_number,
        "signer_name": cert.common_name,
        "signer_pinfl": _mask(cert.pinfl),
        "signer_tin": cert.person_tin,
        "company_tin": cert.legal_tin,
        "cert_valid_to": cert.valid_to.isoformat() if cert.valid_to else None,
        "signing_time": signer.signing_time.isoformat() if signer.signing_time else None,
        "timestamp_time": signer.timestamp_time.isoformat() if signer.timestamp_time else None,
    }


async def _build_signature_container(db: AsyncSession, v: ContractVersion, actor: User) -> None:
    """When every party signed with E-IMZO, merge the signatures into one .p7s (best effort)."""
    approvals = await list_for_version(db, v.id)
    if len(approvals) < 2 or any(a.method != ApprovalMethod.EIMZO for a in approvals):
        return
    try:
        client = eimzo.EimzoClient()
        blobs = []
        for a in approvals:
            row = await files.get_file(db, uuid.UUID(a.proof["pkcs7_file_id"]))
            blobs.append(base64.b64encode(await files.read_bytes(row)).decode())
        merged = blobs[0]
        for other in blobs[1:]:
            merged = await client.join(merged, other)
        stored = await files.save_bytes(
            db,
            data=base64.b64decode(merged),
            filename=f"contract-v{v.number}-signed.p7s",
            declared_mime="application/pkcs7-signature",
            trusted_mime="application/pkcs7-signature",
            owner_id=actor.id,
            purpose="signature",
        )
        v.signed_container_file_id = stored.id
    except AppError as e:  # activation must not fail because the optional container could not be built
        log.warning("eimzo_join_failed", extra={"version_id": str(v.id), "error": e.code})
