from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_client, get_request_id
from app.core.crypto import canonical_json, sha256_hex
from app.core.timeutils import ensure_utc, utcnow
from app.modules.audit.models import AuditLog

_PG_ADVISORY_KEY = 0x1E7A0D17  # serialises chain appends across connections


def _row_digest(prev_hash: str | None, row: AuditLog) -> str:
    body = {
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "action": row.action,
        "entity": row.entity,
        "entity_id": row.entity_id,
        "meta": row.meta,
        "ip": row.ip,
        "at": ensure_utc(row.at).isoformat(),
    }
    return sha256_hex((prev_hash or "").encode() + canonical_json(body))


async def record(
    db: AsyncSession,
    *,
    action: str,
    entity: str,
    entity_id: Any = None,
    actor_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry inside the caller's transaction."""
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_ADVISORY_KEY})
    prev_hash = await db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    client = get_client()
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        # normalise (UUID/Decimal/datetime -> str) so the digest survives a DB round trip
        meta=json.loads(canonical_json(meta or {})),
        ip=client.ip,
        user_agent=(client.user_agent or "")[:255] or None,
        request_id=get_request_id(),
        at=utcnow().replace(microsecond=0),
        prev_hash=prev_hash,
    )
    row.hash = _row_digest(prev_hash, row)
    db.add(row)
    await db.flush()
    return row


async def verify_chain(db: AsyncSession, *, batch: int = 1000) -> dict[str, Any]:
    """Walk the whole chain; return the first broken link if any."""
    prev: str | None = None
    checked = 0
    last_id = 0
    while True:
        rows = (
            await db.scalars(select(AuditLog).where(AuditLog.id > last_id).order_by(AuditLog.id).limit(batch))
        ).all()
        if not rows:
            break
        for row in rows:
            if row.prev_hash != prev or _row_digest(prev, row) != row.hash:
                return {"ok": False, "checked": checked, "broken_at_id": row.id}
            prev = row.hash
            checked += 1
            last_id = row.id
    return {"ok": True, "checked": checked, "head": prev}
