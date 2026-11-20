from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutils import WorkCalendar
from app.modules.calc.models import BhmRate, CalendarDay, DayKind


async def load_calendar(db: AsyncSession, start: date, end: date) -> WorkCalendar:
    rows = (await db.scalars(select(CalendarDay).where(CalendarDay.day >= start, CalendarDay.day <= end))).all()
    return WorkCalendar.build(
        holidays=[r.day for r in rows if r.kind == DayKind.HOLIDAY],
        extra_working_days=[r.day for r in rows if r.kind == DayKind.WORKING],
    )


async def bhm_on(db: AsyncSession, on: date) -> Decimal:
    amount = await db.scalar(
        select(BhmRate.amount).where(BhmRate.valid_from <= on).order_by(BhmRate.valid_from.desc()).limit(1)
    )
    if amount is None:
        raise NotFound("BHM rate is not configured for this date", code="bhm_missing")
    return Decimal(amount)


def _money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class DeadlineResult:
    start: date
    end: date
    days: int
    kind: Literal["calendar", "working"]
    shifted: bool


async def calculate_deadline(
    db: AsyncSession, *, start: date, days: int, kind: Literal["calendar", "working"]
) -> DeadlineResult:
    cal = await load_calendar(db, start, start + timedelta(days=days * 2 + 40))
    if kind == "working":
        end = cal.add_working_days(start, days)
        return DeadlineResult(start, end, days, kind, shifted=False)
    raw_end = start + timedelta(days=days)
    end = cal.next_working_day(raw_end)
    return DeadlineResult(start, end, days, kind, shifted=end != raw_end)


@dataclass(frozen=True, slots=True)
class PenaltyResult:
    principal: Decimal
    days_overdue: int
    rate_percent_per_day: Decimal
    raw_amount: Decimal
    cap_amount: Decimal | None
    amount: Decimal


def calculate_penalty(
    *,
    principal: Decimal,
    due: date,
    paid_on: date,
    rate_percent_per_day: Decimal,
    max_percent_of_principal: Decimal | None = None,
) -> PenaltyResult:
    """Neustoyka (penya): principal * rate% * days, optionally capped."""
    if principal <= 0 or rate_percent_per_day < 0:
        raise ValidationFailed("Principal must be positive and rate non-negative", code="penalty_input")
    days = max((paid_on - due).days, 0)
    raw = _money(principal * rate_percent_per_day / Decimal(100) * days)
    cap = _money(principal * max_percent_of_principal / Decimal(100)) if max_percent_of_principal else None
    amount = min(raw, cap) if cap is not None else raw
    return PenaltyResult(principal, days, rate_percent_per_day, raw, cap, amount)


async def upsert_calendar_day(db: AsyncSession, day: date, kind: DayKind, title: str | None) -> CalendarDay:
    row = await db.get(CalendarDay, day)
    if row is None:
        row = CalendarDay(day=day, kind=kind, title=title)
        db.add(row)
    else:
        row.kind, row.title = kind, title
    await db.flush()
    return row


async def list_calendar(db: AsyncSession, year: int) -> list[CalendarDay]:
    rows = await db.scalars(
        select(CalendarDay)
        .where(and_(CalendarDay.day >= date(year, 1, 1), CalendarDay.day <= date(year, 12, 31)))
        .order_by(CalendarDay.day)
    )
    return list(rows)
