from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, PageParams, require
from app.core.errors import NotFound
from app.core.rbac import Perm
from app.modules.audit import service as audit
from app.modules.moderation.models import ContentReport, ContentTask, ReportStatus, TaskStatus
from app.modules.users.models import User

router = APIRouter(tags=["moderation"])


class ReportIn(BaseModel):
    entity: Literal["legal_rule", "scan_finding", "contract_type"]
    entity_id: uuid.UUID
    message: str = Field(min_length=5, max_length=2000)


class ReportOut(ReportIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: ReportStatus
    resolution: str | None
    created_at: datetime


class ReportResolve(BaseModel):
    status: Literal[ReportStatus.RESOLVED, ReportStatus.REJECTED]
    resolution: str = Field(min_length=2)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    entity: str
    entity_id: uuid.UUID
    reason: str
    status: TaskStatus
    created_at: datetime


@router.post(
    "/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Noto'g'ri xulosa haqida shikoyat",
)
async def create_report(body: ReportIn, db: DB, user: CurrentUser) -> ReportOut:
    r = ContentReport(**body.model_dump(), user_id=user.id)
    db.add(r)
    await db.flush()
    return ReportOut.model_validate(r)


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    db: DB,
    page: PageParams,
    _: Annotated[User, Depends(require(Perm.MODERATION))],
    status_: ReportStatus = ReportStatus.OPEN,
) -> list[ReportOut]:
    stmt = (
        select(ContentReport)
        .where(ContentReport.status == status_)
        .order_by(ContentReport.created_at)
        .limit(page.limit)
        .offset(page.offset)
    )
    return [ReportOut.model_validate(r) for r in await db.scalars(stmt)]


@router.post("/reports/{report_id}/resolve", response_model=ReportOut)
async def resolve_report(
    report_id: uuid.UUID,
    body: ReportResolve,
    db: DB,
    user: Annotated[User, Depends(require(Perm.MODERATION))],
) -> ReportOut:
    r = await db.get(ContentReport, report_id)
    if r is None:
        raise NotFound("Report not found")
    r.status, r.resolution, r.resolved_by = body.status, body.resolution, user.id
    await audit.record(
        db,
        action="report.resolve",
        entity="content_report",
        entity_id=r.id,
        actor_id=user.id,
        meta={"status": body.status.value},
    )
    return ReportOut.model_validate(r)


@router.get("/cms/tasks", response_model=list[TaskOut], summary="Muharrir vazifalari")
async def open_tasks(db: DB, page: PageParams, _: Annotated[User, Depends(require(Perm.RULES_WRITE))]) -> list[TaskOut]:
    rows = await db.scalars(
        select(ContentTask)
        .where(ContentTask.status == TaskStatus.OPEN)
        .order_by(ContentTask.created_at)
        .limit(page.limit)
        .offset(page.offset)
    )
    return [TaskOut.model_validate(t) for t in rows]


@router.post("/cms/tasks/{task_id}/done", response_model=TaskOut)
async def close_task(task_id: uuid.UUID, db: DB, user: Annotated[User, Depends(require(Perm.RULES_WRITE))]) -> TaskOut:
    t = await db.get(ContentTask, task_id)
    if t is None:
        raise NotFound("Task not found")
    t.status = TaskStatus.DONE
    await audit.record(db, action="task.done", entity="content_task", entity_id=t.id, actor_id=user.id)
    return TaskOut.model_validate(t)
