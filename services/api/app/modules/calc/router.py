from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DB, require
from app.core.rbac import Perm
from app.core.timeutils import today_local
from app.modules.audit import service as audit
from app.modules.calc import service
from app.modules.calc.models import DayKind
from app.modules.users.models import User

router = APIRouter(prefix="/calc", tags=["calculators"])


class DeadlineIn(BaseModel):
    start: date
    days: int = Field(ge=0, le=3650)
    kind: Literal["calendar", "working"] = "calendar"


class DeadlineOut(BaseModel):
    start: date
    end: date
    days: int
    kind: str
    shifted: bool = Field(description="Muddat dam olish kuniga tushgani uchun keyingi ish kuniga surildi")


class PenaltyIn(BaseModel):
    principal: Decimal = Field(gt=0)
    due: date
    paid_on: date
    rate_percent_per_day: Decimal = Field(ge=0, le=100)
    max_percent_of_principal: Decimal | None = Field(default=None, ge=0, le=100)


class PenaltyOut(BaseModel):
    principal: Decimal
    days_overdue: int
    rate_percent_per_day: Decimal
    raw_amount: Decimal
    cap_amount: Decimal | None
    amount: Decimal


class BhmOut(BaseModel):
    on_date: date
    amount: Decimal


class CalendarDayIn(BaseModel):
    day: date
    kind: DayKind
    title: str | None = None


class CalendarDayOut(CalendarDayIn):
    model_config = ConfigDict(from_attributes=True)


@router.post("/deadline", response_model=DeadlineOut, summary="Shartnoma muddatini hisoblash (ish/taqvim kunlari)")
async def deadline(body: DeadlineIn, db: DB) -> DeadlineOut:
    r = await service.calculate_deadline(db, start=body.start, days=body.days, kind=body.kind)
    return DeadlineOut(start=r.start, end=r.end, days=r.days, kind=r.kind, shifted=r.shifted)


@router.post("/penalty", response_model=PenaltyOut, summary="Neustoyka (penya) hisoblash")
async def penalty(body: PenaltyIn) -> PenaltyOut:
    r = service.calculate_penalty(**body.model_dump())
    return PenaltyOut(**{f: getattr(r, f) for f in PenaltyOut.model_fields})


@router.get("/bhm", response_model=BhmOut, summary="Bazaviy hisoblash miqdori (BHM)")
async def bhm(db: DB, on_date: date | None = None) -> BhmOut:
    on = on_date or today_local()
    return BhmOut(on_date=on, amount=await service.bhm_on(db, on))


@router.get("/calendar", response_model=list[CalendarDayOut], summary="Bayram va ko'chirilgan kunlar")
async def calendar(db: DB, year: Annotated[int, Query(ge=2000, le=2100)]) -> list[CalendarDayOut]:
    return [CalendarDayOut.model_validate(d) for d in await service.list_calendar(db, year)]


@router.put("/calendar", response_model=CalendarDayOut)
async def put_calendar_day(
    body: CalendarDayIn, db: DB, user: Annotated[User, Depends(require(Perm.CALENDAR_WRITE))]
) -> CalendarDayOut:
    row = await service.upsert_calendar_day(db, body.day, body.kind, body.title)
    await audit.record(
        db,
        action="calendar.upsert",
        entity="calendar_day",
        entity_id=str(body.day),
        actor_id=user.id,
        meta={"kind": body.kind.value},
    )
    return CalendarDayOut.model_validate(row)
