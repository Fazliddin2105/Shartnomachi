from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DB, PageParams, require
from app.core.rbac import Perm
from app.modules.audit import service
from app.modules.audit.models import AuditLog
from app.modules.users.models import User

router = APIRouter(prefix="/admin/audit", tags=["admin"])
Auditor = Annotated[User, Depends(require(Perm.AUDIT_READ))]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: uuid.UUID | None
    action: str
    entity: str
    entity_id: str | None
    meta: dict[str, Any]
    ip: str | None
    at: datetime
    hash: str


@router.get("", response_model=list[AuditOut])
async def list_audit(
    db: DB,
    _: Auditor,
    page: PageParams,
    entity: str | None = None,
    entity_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
) -> list[AuditOut]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [AuditOut.model_validate(r) for r in await db.scalars(stmt.limit(page.limit).offset(page.offset))]


@router.get("/verify", summary="Audit zanjiri yaxlitligini tekshirish")
async def verify(db: DB, _: Auditor) -> dict[str, Any]:
    return await service.verify_chain(db)
