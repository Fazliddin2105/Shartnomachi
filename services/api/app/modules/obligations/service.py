from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from dateutil.rrule import rrulestr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutils import today_local, utcnow
from app.modules.audit import service as audit
from app.modules.obligations.models import (
    Obligation,
    ObligationKind,
    ObligationSource,
    ObligationStatus,
)
from app.modules.reminders import planner
from app.modules.reminders import service as reminders
from app.modules.users.models import User


def validate_rrule(rule: str) -> None:
    try:
        rrulestr(rule)
    except (ValueError, TypeError) as e:
        raise ValidationFailed(f"Invalid recurrence rule: {e}", code="rrule_invalid") from e


async def create(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    title: str,
    due_date: date,
    kind: ObligationKind = ObligationKind.DUTY,
    source: ObligationSource = ObligationSource.MANUAL,
    amount: Decimal | None = None,
    currency: str = "UZS",
    description: str | None = None,
    recurrence_rule: str | None = None,
    recurrence_until: date | None = None,
    contract_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    confirmed: bool = True,
    source_clause_ref: str | None = None,
    shift_to_working_day: bool = True,
) -> Obligation:
    if recurrence_rule:
        validate_rrule(recurrence_rule)
    ob = Obligation(
        owner_id=owner_id,
        title=title,
        due_date=due_date,
        kind=kind,
        source=source,
        amount=amount,
        currency=currency,
        description=description,
        recurrence_rule=recurrence_rule,
        recurrence_until=recurrence_until,
        contract_id=contract_id,
        party_id=party_id,
        confirmed=confirmed,
        source_clause_ref=source_clause_ref,
        shift_to_working_day=shift_to_working_day,
    )
    ob.series_id = ob.id = uuid.uuid4()
    if due_date < today_local():
        ob.status = ObligationStatus.OVERDUE
    db.add(ob)
    await db.flush()
    await reminders.schedule_for(db, ob)
    return ob


async def get_owned(db: AsyncSession, obligation_id: uuid.UUID, user: User) -> Obligation:
    ob = await db.get(Obligation, obligation_id)
    if ob is None or ob.owner_id != user.id:
        raise NotFound("Obligation not found")
    return ob


async def complete(
    db: AsyncSession, ob: Obligation, *, actor: User, proof_file_id: uuid.UUID | None = None
) -> Obligation | None:
    """Mark done, cancel remaining reminders, spawn the next recurring occurrence."""
    if ob.status in (ObligationStatus.DONE, ObligationStatus.CANCELLED):
        raise ValidationFailed("Obligation is already closed", code="obligation_closed")
    ob.status, ob.completed_at, ob.proof_file_id = ObligationStatus.DONE, utcnow(), proof_file_id
    await reminders.cancel_pending(db, ob.id)
    await audit.record(
        db,
        action="obligation.done",
        entity="obligation",
        entity_id=ob.id,
        actor_id=actor.id,
        meta={"proof_file_id": str(proof_file_id) if proof_file_id else None},
    )
    if not ob.recurrence_rule:
        return None
    nxt = planner.next_occurrence(ob.recurrence_rule, after=ob.due_date, until=ob.recurrence_until)
    if nxt is None:
        return None
    new = Obligation(
        owner_id=ob.owner_id,
        contract_id=ob.contract_id,
        party_id=ob.party_id,
        source=ob.source,
        kind=ob.kind,
        title=ob.title,
        description=ob.description,
        amount=ob.amount,
        currency=ob.currency,
        due_date=nxt,
        shift_to_working_day=ob.shift_to_working_day,
        recurrence_rule=ob.recurrence_rule,
        recurrence_until=ob.recurrence_until,
        series_id=ob.series_id,
        occurrence_no=ob.occurrence_no + 1,
        confirmed=True,
        source_clause_ref=ob.source_clause_ref,
    )
    db.add(new)
    await db.flush()
    await reminders.schedule_for(db, new)
    return new


async def cancel(db: AsyncSession, ob: Obligation, *, actor: User) -> None:
    ob.status = ObligationStatus.CANCELLED
    await reminders.cancel_pending(db, ob.id)
    await audit.record(db, action="obligation.cancel", entity="obligation", entity_id=ob.id, actor_id=actor.id)


@dataclass(frozen=True, slots=True)
class Dashboard:
    upcoming_30d: list[Obligation]
    overdue: list[Obligation]
    unpaid_total: dict[str, Decimal]
    unconfirmed: int
    risk: str  # low | medium | high


async def dashboard(db: AsyncSession, user: User) -> Dashboard:
    today = today_local()
    active = [ObligationStatus.PENDING, ObligationStatus.REMINDED]
    upcoming = list(
        await db.scalars(
            select(Obligation)
            .where(
                Obligation.owner_id == user.id,
                Obligation.status.in_(active),
                Obligation.due_date <= today + timedelta(days=30),
                Obligation.confirmed.is_(True),
            )
            .order_by(Obligation.due_date)
        )
    )
    overdue = list(
        await db.scalars(
            select(Obligation)
            .where(Obligation.owner_id == user.id, Obligation.status == ObligationStatus.OVERDUE)
            .order_by(Obligation.due_date)
        )
    )
    sums = await db.execute(
        select(Obligation.currency, func.coalesce(func.sum(Obligation.amount), 0))
        .where(
            Obligation.owner_id == user.id,
            Obligation.kind == ObligationKind.DUTY,
            Obligation.status.in_([*active, ObligationStatus.OVERDUE]),
        )
        .group_by(Obligation.currency)
    )
    unconfirmed = await db.scalar(
        select(func.count(Obligation.id)).where(
            Obligation.owner_id == user.id,
            Obligation.confirmed.is_(False),
            Obligation.status != ObligationStatus.CANCELLED,
        )
    )
    soon = [o for o in upcoming if (o.due_date - today).days <= 3 and o.kind == ObligationKind.DUTY]
    risk = "high" if overdue else "medium" if soon else "low"
    return Dashboard(upcoming, overdue, {c: Decimal(str(v)) for c, v in sums.all()}, unconfirmed or 0, risk)
