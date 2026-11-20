"""Personal archive: every participant gets the signed contract filed when all parties have signed."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.timeutils import utcnow
from app.modules.contracts import service
from app.modules.contracts.models import (
    ArchivedContract,
    Contract,
    ContractApproval,
    ContractVersion,
    PartyRole,
)


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
