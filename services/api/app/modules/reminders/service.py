"""Reminder persistence and dispatch (spec §8, steps 1-7)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable
from app.core.timeutils import ensure_utc, to_local, today_local, utcnow
from app.modules.calc.service import load_calendar
from app.modules.notifications import channels as ch
from app.modules.obligations.models import Obligation, ObligationStatus, Reminder, ReminderStatus
from app.modules.reminders import planner
from app.modules.users.models import User

log = logging.getLogger(__name__)

_ACTIVE = (ObligationStatus.PENDING, ObligationStatus.REMINDED, ObligationStatus.OVERDUE)


async def cancel_pending(db: AsyncSession, obligation_id: uuid.UUID) -> None:
    await db.execute(
        update(Reminder)
        .where(
            Reminder.obligation_id == obligation_id,
            Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.QUEUED]),
        )
        .values(status=ReminderStatus.CANCELLED)
    )


async def schedule_for(db: AsyncSession, obligation: Obligation, *, now: datetime | None = None) -> list[Reminder]:
    """(Re)build reminders after an obligation is created or its due date changed."""
    s = get_settings()
    now = now or utcnow()
    await cancel_pending(db, obligation.id)
    await db.flush()
    if obligation.status not in _ACTIVE or not obligation.confirmed:
        return []
    # Never re-send a reminder that already went out for the same day/offset/channel.
    already_sent = {
        (r.offset_days, r.channel, to_local(ensure_utc(r.scheduled_at)).date())
        for r in await db.scalars(
            select(Reminder).where(Reminder.obligation_id == obligation.id, Reminder.status == ReminderStatus.SENT)
        )
    }

    user = await db.get(User, obligation.owner_id)
    if user is None:
        return []
    cal = await load_calendar(db, obligation.due_date, obligation.due_date + timedelta(days=30))
    due = planner.effective_due(obligation.due_date, cal, obligation.shift_to_working_day)
    rows: list[Reminder] = []
    for p in planner.plan(due=due, offsets=s.reminder_offsets_days, send_hour=s.reminder_send_hour, now=now):
        for channel in ch.user_channels(user):
            if (p.offset_days, channel, to_local(p.scheduled_at).date()) in already_sent:
                continue
            rows.append(
                Reminder(
                    obligation_id=obligation.id,
                    user_id=user.id,
                    offset_days=p.offset_days,
                    channel=channel,
                    scheduled_at=p.scheduled_at,
                )
            )
    db.add_all(rows)
    await db.flush()
    return rows


def _message(ob: Obligation, offset: int) -> ch.Message:
    due = ob.due_date.strftime("%d.%m.%Y")
    when = "bugun" if offset == 0 else f"{offset} kun qoldi"
    amount = f" Summa: {ob.amount:,.0f} {ob.currency}.".replace(",", " ") if ob.amount else ""
    kind = "Majburiyat" if ob.kind.value == "duty" else "Huquq"
    return ch.Message(
        type="obligation.reminder",
        title=f"{kind}: {ob.title}",
        body=f"Muddat: {due} ({when}).{amount}",
        payload={
            "obligation_id": str(ob.id),
            "contract_id": str(ob.contract_id) if ob.contract_id else None,
            "offset_days": offset,
        },
    )


async def claim_due(db: AsyncSession, *, now: datetime | None = None, limit: int = 200) -> list[uuid.UUID]:
    """Step 2: pick `scheduled_at <= now AND status = pending` rows and mark them queued.

    `FOR UPDATE SKIP LOCKED` lets several workers run concurrently on Postgres.
    """
    now = now or utcnow()
    stmt = (
        select(Reminder)
        .where(
            Reminder.status == ReminderStatus.PENDING,
            Reminder.scheduled_at <= now,
            (Reminder.next_attempt_at.is_(None)) | (Reminder.next_attempt_at <= now),
        )
        .order_by(Reminder.scheduled_at)
        .limit(limit)
    )
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    rows = (await db.scalars(stmt)).all()
    for r in rows:
        r.status = ReminderStatus.QUEUED
    await db.flush()
    return [r.id for r in rows]


async def deliver(db: AsyncSession, reminder_id: uuid.UUID, *, now: datetime | None = None) -> ReminderStatus:
    """Step 3: send through the channel; retry with backoff, then fall back to in-app."""
    s = get_settings()
    now = now or utcnow()
    r = await db.get(Reminder, reminder_id)
    if r is None or r.status != ReminderStatus.QUEUED:
        return r.status if r else ReminderStatus.CANCELLED
    ob = await db.get(Obligation, r.obligation_id)
    user = await db.get(User, r.user_id)
    if ob is None or user is None or ob.status not in _ACTIVE:
        r.status = ReminderStatus.CANCELLED
        return r.status

    msg = _message(ob, r.offset_days)
    r.attempts += 1
    try:
        await ch.send(db, user, r.channel, msg)
    except Exception as e:
        r.last_error = str(e)[:500]
        permanent = isinstance(e, IntegrationUnavailable)
        if permanent or r.attempts >= s.reminder_max_attempts:
            r.status = ReminderStatus.FAILED
            if r.channel != "in_app":
                await ch.send(db, user, "in_app", msg)  # fallback channel
        else:
            r.status = ReminderStatus.PENDING
            r.next_attempt_at = now + timedelta(minutes=2**r.attempts)
        log.warning("reminder_failed", extra={"reminder_id": str(r.id), "channel": r.channel, "error": r.last_error})
        return r.status

    r.status, r.sent_at = ReminderStatus.SENT, now
    if ob.status == ObligationStatus.PENDING:
        ob.status = ObligationStatus.REMINDED
    return r.status


async def mark_overdue(db: AsyncSession) -> int:
    today = today_local()
    res = await db.execute(
        update(Obligation)
        .where(
            Obligation.status.in_([ObligationStatus.PENDING, ObligationStatus.REMINDED]),
            Obligation.due_date < today,
        )
        .values(status=ObligationStatus.OVERDUE)
    )
    return res.rowcount or 0  # type: ignore[attr-defined]


async def run_dispatch_cycle(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """One scheduler tick used by both in-process loop and the ARQ worker."""
    ids = await claim_due(db, now=now)
    stats = {"claimed": len(ids), "sent": 0, "failed": 0, "retry": 0}
    for rid in ids:
        st = await deliver(db, rid, now=now)
        if st == ReminderStatus.SENT:
            stats["sent"] += 1
        elif st == ReminderStatus.FAILED:
            stats["failed"] += 1
        elif st == ReminderStatus.PENDING:
            stats["retry"] += 1
    stats["overdue"] = await mark_overdue(db)
    return stats
