from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, File, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, PageParams
from app.core.errors import Conflict, ValidationFailed
from app.modules.files import service as files
from app.modules.obligations import service
from app.modules.obligations.models import (
    Obligation,
    ObligationKind,
    ObligationSource,
    ObligationStatus,
)
from app.modules.reminders import service as reminders

router = APIRouter(prefix="/obligations", tags=["obligations"])


class ObligationIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    kind: ObligationKind = ObligationKind.DUTY
    description: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="UZS", pattern="^[A-Z]{3}$")
    due_date: date
    recurrence_rule: str | None = Field(default=None, examples=["FREQ=MONTHLY;BYMONTHDAY=10"])
    recurrence_until: date | None = None
    shift_to_working_day: bool = True


class ObligationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    due_date: date | None = None
    confirmed: bool | None = Field(default=None, description="AI ajratgan majburiyatni tasdiqlash")
    status: ObligationStatus | None = Field(default=None, description="done | cancelled")


class ObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    contract_id: uuid.UUID | None
    source: ObligationSource
    kind: ObligationKind
    title: str
    description: str | None
    amount: Decimal | None
    currency: str
    due_date: date
    recurrence_rule: str | None
    occurrence_no: int
    status: ObligationStatus
    confirmed: bool
    completed_at: datetime | None
    proof_file_id: uuid.UUID | None


class DashboardOut(BaseModel):
    upcoming_30d: list[ObligationOut]
    overdue: list[ObligationOut]
    unpaid_total: dict[str, Decimal]
    unconfirmed: int
    risk: str


@router.get("", response_model=list[ObligationOut], summary="Majburiyatlar ro'yxati")
async def list_obligations(
    db: DB,
    user: CurrentUser,
    page: PageParams,
    status_: ObligationStatus | None = None,
    recurring: bool | None = None,
    contract_id: uuid.UUID | None = None,
) -> list[ObligationOut]:
    stmt = select(Obligation).where(Obligation.owner_id == user.id)
    if status_:
        stmt = stmt.where(Obligation.status == status_)
    if recurring is not None:
        stmt = stmt.where(
            Obligation.recurrence_rule.is_not(None) if recurring else Obligation.recurrence_rule.is_(None)
        )
    if contract_id:
        stmt = stmt.where(Obligation.contract_id == contract_id)
    stmt = stmt.order_by(Obligation.due_date).limit(page.limit).offset(page.offset)
    return [ObligationOut.model_validate(o) for o in await db.scalars(stmt)]


@router.get("/dashboard", response_model=DashboardOut, summary="Keyingi 30 kun, to'lanmagan summa, xavf")
async def get_dashboard(db: DB, user: CurrentUser) -> DashboardOut:
    d = await service.dashboard(db, user)
    return DashboardOut(
        upcoming_30d=[ObligationOut.model_validate(o) for o in d.upcoming_30d],
        overdue=[ObligationOut.model_validate(o) for o in d.overdue],
        unpaid_total=d.unpaid_total,
        unconfirmed=d.unconfirmed,
        risk=d.risk,
    )


@router.post("", response_model=ObligationOut, status_code=status.HTTP_201_CREATED)
async def create_obligation(body: ObligationIn, db: DB, user: CurrentUser) -> ObligationOut:
    ob = await service.create(db, owner_id=user.id, **body.model_dump())
    return ObligationOut.model_validate(ob)


@router.patch("/{obligation_id}", response_model=ObligationOut, summary="Bajarildi / o'zgartirish")
async def patch_obligation(obligation_id: uuid.UUID, body: ObligationPatch, db: DB, user: CurrentUser) -> ObligationOut:
    ob = await service.get_owned(db, obligation_id, user)
    changes = body.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    for k, v in changes.items():
        setattr(ob, k, v)
    if new_status == ObligationStatus.DONE:
        await service.complete(db, ob, actor=user)
    elif new_status == ObligationStatus.CANCELLED:
        await service.cancel(db, ob, actor=user)
    elif new_status == ObligationStatus.PENDING:
        # «bajarilmadi» — undo a mistaken completion/cancellation; reminders are rescheduled
        ob.status, ob.completed_at = ObligationStatus.PENDING, None
        await reminders.schedule_for(db, ob)
    elif new_status is not None:
        raise ValidationFailed("Only 'done', 'cancelled' or 'pending' can be set manually", code="status_invalid")
    elif {"due_date", "confirmed"} & changes.keys():
        await reminders.schedule_for(db, ob)
    await db.flush()
    return ObligationOut.model_validate(ob)


@router.post(
    "/{obligation_id}/complete", response_model=ObligationOut, summary="Bajarildi + isbot (chek/rasm) biriktirish"
)
async def complete_with_proof(
    obligation_id: uuid.UUID, db: DB, user: CurrentUser, proof: UploadFile | None = File(default=None)
) -> ObligationOut:
    ob = await service.get_owned(db, obligation_id, user)
    proof_id = None
    if proof is not None:
        stored = await files.save_bytes(
            db,
            data=await proof.read(),
            filename=proof.filename or "proof",
            declared_mime=proof.content_type,
            owner_id=user.id,
            purpose="proof",
        )
        proof_id = stored.id
    await service.complete(db, ob, actor=user, proof_file_id=proof_id)
    return ObligationOut.model_validate(ob)


@router.delete(
    "/{obligation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="O'zi qo'shgan / skanerdan olingan eslatmani o'chirish (shartnomadagi majburiyat o'chmaydi)",
)
async def delete_obligation(obligation_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    ob = await service.get_owned(db, obligation_id, user)
    if ob.source == ObligationSource.CONTRACT:
        raise Conflict(
            "Obligations of a signed contract cannot be deleted; mark them done or cancelled",
            code="obligation_from_contract",
        )
    await db.delete(ob)
