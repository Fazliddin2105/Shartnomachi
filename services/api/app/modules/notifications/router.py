from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser, PageParams
from app.core.timeutils import utcnow
from app.modules.notifications.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: str
    title: str
    body: str
    payload: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


@router.get("", response_model=NotificationList)
async def list_notifications(
    db: DB, user: CurrentUser, page: PageParams, unread_only: bool = False
) -> NotificationList:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = await db.scalars(stmt.order_by(Notification.created_at.desc()).limit(page.limit).offset(page.offset))
    unread = await db.scalar(
        select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return NotificationList(items=[NotificationOut.model_validate(r) for r in rows], unread=unread or 0)


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(db: DB, user: CurrentUser, ids: list[uuid.UUID] | None = None) -> None:
    stmt = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    await db.execute(stmt.values(read_at=utcnow()))
