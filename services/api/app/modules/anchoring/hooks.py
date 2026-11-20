"""Domain events that produce anchor leaves (kept apart from the generic service to avoid import cycles)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.anchoring import service
from app.modules.anchoring.models import AnchorLeaf, LeafKind
from app.modules.cases.models import CaseAttachment
from app.modules.contracts.models import ContractApproval, ContractVersion
from app.modules.users.models import User


async def contract_signed(
    db: AsyncSession, *, version: ContractVersion, approvals: list[ContractApproval]
) -> AnchorLeaf:
    """All parties approved a version: anchor content hash + who (committed) + when."""
    signers: list[dict[str, Any]] = []
    openings: dict[str, Any] = {}
    for a in approvals:
        user = await db.get(User, a.user_id)
        identity: dict[str, Any] = {"user_id": str(a.user_id)}
        if user is not None and user.verified_pinfl_hash and user.profile and user.profile.pinfl:
            identity["pinfl"] = user.profile.pinfl  # government-verified (OneID / E-IMZO)
        if a.proof.get("cert_serial"):
            identity["eri_cert_serial"] = a.proof["cert_serial"]
        commitment, salt = service.commit(identity)
        signers.append(
            {
                "commitment": commitment,
                "method": a.method.value,
                "signed_at": a.signed_at.isoformat(),
                "pkcs7_sha256": a.proof.get("pkcs7_sha256"),
            }
        )
        openings[str(a.user_id)] = {"salt": salt, "identity": identity, "commitment": commitment}
    payload = {
        "contract_id": str(version.contract_id),
        "version": version.number,
        "content_sha256": version.sha256,
        "signers": signers,
    }
    return await service.add_leaf(
        db, kind=LeafKind.CONTRACT_SIGNED, ref_id=version.id, payload=payload, secrets=openings
    )


async def case_attachment(db: AsyncSession, *, attachment: CaseAttachment, case_id: Any) -> AnchorLeaf:
    """Lawyer evidence: proves the file existed unchanged at this time (no personal data in the leaf)."""
    return await service.add_leaf(
        db,
        kind=LeafKind.CASE_ATTACHMENT,
        ref_id=attachment.id,
        payload={
            "case_id": str(case_id),
            "file_sha256": attachment.sha256,
            "type": attachment.type.value,
            "captured_at": attachment.captured_at.isoformat(),
        },
    )
