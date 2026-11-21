"""Personal archive: every participant gets the signed contract filed when all parties have signed."""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutils import utcnow
from app.modules.contracts import service
from app.modules.contracts.models import (
    ArchivedContract,
    ArchiveDocument,
    Contract,
    ContractApproval,
    ContractVersion,
    PartyRole,
)
from app.modules.files import service as files
from app.modules.files.models import StoredFile


def _side(p: Any) -> str | None:
    if p.role in (PartyRole.A, PartyRole.B):
        return p.role.value
    return p.represents.value if p.represents else None


async def archive_signed(db: AsyncSession, c: Contract, v: ContractVersion) -> list[ArchivedContract]:
    """Called once the contract becomes active. Idempotent per (user, version)."""
    names = service.party_names(c)
    signed = list(await db.scalars(select(ContractApproval.signed_at).where(ContractApproval.version_id == v.id)))
    signed_at = max(signed) if signed else utcnow()
    users: dict[uuid.UUID, str | None] = {}
    for p in c.parties:
        if p.user_id is not None:
            users.setdefault(p.user_id, _side(p))
    users.setdefault(c.owner_id, next((_side(p) for p in c.parties if p.user_id == c.owner_id), None))
    out = []
    for uid, side in users.items():
        if await db.scalar(
            select(ArchivedContract.id).where(ArchivedContract.user_id == uid, ArchivedContract.version_id == v.id)
        ):
            continue
        other = {"A": "B", "B": "A"}.get(side or "")
        item = ArchivedContract(
            user_id=uid,
            contract_id=c.id,
            version_id=v.id,
            version_number=v.number,
            sha256=v.sha256,
            side=side,
            title=c.title,
            type_code=c.contract_type.code if c.contract_type else None,
            counterparty=names.get(other) if other else None,
            total_amount=c.total_amount,
            currency=c.currency,
            starts_on=c.starts_on,
            ends_on=c.ends_on,
            signed_at=signed_at,
            tags=[],
        )
        db.add(item)
        out.append(item)
    await db.flush()
    return out


def item_out(a: ArchivedContract, status: str | None = None) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "contract_id": str(a.contract_id),
        "contract_status": status,
        "title": a.title,
        "type_code": a.type_code,
        "side": a.side,
        "counterparty": a.counterparty,
        "total_amount": str(a.total_amount) if a.total_amount is not None else None,
        "currency": a.currency,
        "starts_on": a.starts_on.isoformat() if a.starts_on else None,
        "ends_on": a.ends_on.isoformat() if a.ends_on else None,
        "version": a.version_number,
        "sha256": a.sha256,
        "signed_at": a.signed_at.isoformat(),
        "archived_at": a.archived_at.isoformat(),
        "note": a.note,
        "tags": a.tags or [],
        "download": {
            "docx": f"/api/v1/contracts/{a.contract_id}/versions/{a.version_number}/download?format=docx",
            "signature_p7s": f"/api/v1/contracts/{a.contract_id}/versions/{a.version_number}/signature.p7s",
        },
    }


async def list_items(
    db: AsyncSession, user_id: uuid.UUID, *, q: str | None, type_code: str | None, limit: int, offset: int
) -> list[dict[str, Any]]:
    stmt = (
        select(ArchivedContract, Contract.status)
        .join(Contract, Contract.id == ArchivedContract.contract_id)
        .where(ArchivedContract.user_id == user_id)
    )
    if type_code:
        stmt = stmt.where(ArchivedContract.type_code == type_code)
    if q:
        stmt = stmt.where(or_(ArchivedContract.title.ilike(f"%{q}%"), ArchivedContract.type_code.ilike(f"%{q}%")))
    stmt = stmt.order_by(ArchivedContract.signed_at.desc()).limit(limit).offset(offset)
    return [item_out(a, st.value) for a, st in (await db.execute(stmt)).tuples()]


async def get_item(db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> dict[str, Any]:
    a = await db.get(ArchivedContract, item_id)
    if a is None or a.user_id != user_id:
        raise NotFound("Archive item not found")
    c = await db.get(Contract, a.contract_id)
    v = await db.get(ContractVersion, a.version_id)
    assert c is not None and v is not None
    approvals = list(
        await db.scalars(
            select(ContractApproval).where(ContractApproval.version_id == v.id).order_by(ContractApproval.signed_at)
        )
    )
    roles = {p.id: p.role.value for p in c.parties}
    out = item_out(a, c.status.value)
    out["integrity"] = service.verify_integrity(v)
    out["signatures"] = [
        {
            "side": roles.get(x.party_id),
            "method": x.method.value,
            "signed_at": x.signed_at.isoformat(),
            "sha256": x.sha256,
            "proof": {k: x.proof.get(k) for k in ("phone_masked", "cert_serial", "signer_name") if x.proof.get(k)},
        }
        for x in approvals
    ]
    out["documents"] = await list_documents(db, user_id, archive_id=a.id)
    return out


async def update_item(
    db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID, *, note: str | None, tags: list[str] | None
) -> dict[str, Any]:
    a = await db.get(ArchivedContract, item_id)
    if a is None or a.user_id != user_id:
        raise NotFound("Archive item not found")
    if note is not None:
        a.note = note.strip()[:2000] or None
    if tags is not None:
        a.tags = sorted({t.strip()[:40] for t in tags if t.strip()})[:20]
    c = await db.get(Contract, a.contract_id)
    return item_out(a, c.status.value if c else None)


# --- documents filed by the user: payment receipts, addenda, claims -------------------------------------

DOC_KINDS = {
    "receipt": "To'lov cheki",
    "addendum": "Qo'shimcha kelishuv",
    "claim": "Rasmiy talabnoma",
    "other": "Hujjat",
}


def doc_out(d: ArchiveDocument, f: StoredFile | None, contract_title: str | None = None) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "archive_id": str(d.archive_id) if d.archive_id else None,
        "contract_title": contract_title,
        "kind": d.kind,
        "kind_label": DOC_KINDS.get(d.kind, "Hujjat"),
        "title": d.title,
        "description": d.description,
        "amount": f"{d.amount:.2f}" if d.amount is not None else None,
        "currency": d.currency,
        "doc_date": d.doc_date.isoformat() if d.doc_date else None,
        "created_at": d.created_at.isoformat(),
        "file": (
            {
                "name": f.original_name,
                "mime": f.mime,
                "size": f.size,
                "sha256": f.sha256,
                "download": f"/api/v1/archive/documents/{d.id}/file",
            }
            if f
            else None
        ),
    }


async def _own_archive_item(
    db: AsyncSession, user_id: uuid.UUID, archive_id: uuid.UUID | None
) -> ArchivedContract | None:
    if archive_id is None:
        return None
    a = await db.get(ArchivedContract, archive_id)
    if a is None or a.user_id != user_id:
        raise NotFound("Archive item not found")
    return a


async def add_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    title: str,
    kind: str,
    description: str | None,
    amount: Decimal | None,
    doc_date: date | None,
    archive_id: uuid.UUID | None,
    file: tuple[bytes, str, str | None] | None,
) -> dict[str, Any]:
    title = re.sub(r"\s+", " ", title or "").strip()
    if len(title) < 2:
        raise ValidationFailed("Hujjat nomini kiriting", code="doc_title_required")
    if kind not in DOC_KINDS:
        raise ValidationFailed("Unknown document kind", code="doc_kind")
    if amount is not None and amount < 0:
        raise ValidationFailed("Summa manfiy bo'lishi mumkin emas", code="doc_amount")
    a = await _own_archive_item(db, user_id, archive_id)
    stored = None
    if file is not None:
        data, name, mime = file
        if not data:
            raise ValidationFailed("Fayl bo'sh", code="file_empty")
        sniffed = files.sniff_mime(data, mime)  # magic bytes, not the browser's claim
        if not (sniffed.startswith("image/") or sniffed in DOC_MIME):
            raise ValidationFailed("Faqat PDF, rasm (JPG/PNG) yoki DOCX fayl yuklash mumkin", code="file_type")
        stored = await files.save_bytes(
            db, data=data, filename=name, declared_mime=mime, owner_id=user_id, purpose="archive", trusted_mime=sniffed
        )
    d = ArchiveDocument(
        user_id=user_id,
        archive_id=a.id if a else None,
        kind=kind,
        title=title[:255],
        description=(description or "").strip()[:4000] or None,
        amount=amount,
        doc_date=doc_date,
        file_id=stored.id if stored else None,
    )
    db.add(d)
    await db.flush()
    return doc_out(d, stored, a.title if a else None)


DOC_MIME = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


async def list_documents(
    db: AsyncSession, user_id: uuid.UUID, *, archive_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    stmt = (
        select(ArchiveDocument, StoredFile, ArchivedContract.title)
        .outerjoin(StoredFile, StoredFile.id == ArchiveDocument.file_id)
        .outerjoin(ArchivedContract, ArchivedContract.id == ArchiveDocument.archive_id)
        .where(ArchiveDocument.user_id == user_id)
    )
    if archive_id is not None:
        stmt = stmt.where(ArchiveDocument.archive_id == archive_id)
    stmt = stmt.order_by(ArchiveDocument.created_at.desc()).limit(limit).offset(offset)
    return [doc_out(d, f, t) for d, f, t in (await db.execute(stmt)).tuples()]


async def _own_document(db: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID) -> ArchiveDocument:
    d = await db.get(ArchiveDocument, doc_id)
    if d is None or d.user_id != user_id:
        raise NotFound("Document not found")
    return d


async def document_file(db: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID) -> tuple[bytes, StoredFile]:
    d = await _own_document(db, user_id, doc_id)
    if d.file_id is None:
        raise NotFound("Bu hujjatga fayl biriktirilmagan", code="doc_no_file")
    f = await files.get_file(db, d.file_id)
    return await files.read_bytes(f), f


async def delete_document(db: AsyncSession, user_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    d = await _own_document(db, user_id, doc_id)
    file_id = d.file_id
    await db.delete(d)
    await db.flush()
    if file_id:
        await files.delete_file(db, file_id)
