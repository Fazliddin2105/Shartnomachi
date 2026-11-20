from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutils import utcnow
from app.db.base import Base
from app.db.types import JSONType

# BIGSERIAL on Postgres; INTEGER PRIMARY KEY (rowid alias) on SQLite.
_BigId = BigInteger().with_variant(Integer(), "sqlite")


class AuditLog(Base):
    """Append-only, hash-chained audit trail.

    Each row stores `hash = sha256(prev_hash + canonical(row))`, so any later
    modification or deletion breaks the chain and is detectable by
    `AuditService.verify_chain()`. On Postgres a trigger additionally rejects
    UPDATE/DELETE (see the initial migration).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(_BigId, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
