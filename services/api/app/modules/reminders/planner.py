"""Pure reminder scheduling (no I/O) — spec §8.

* Reminders fire 6/3/2/1/0 days before the (working-day-adjusted) due date
  at `send_hour` local time.
* Offsets whose moment already passed are skipped, except a reminder that is
  due *today* but past the hour, which fires immediately.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dateutil.rrule import rrulestr

from app.core.timeutils import WorkCalendar, local_datetime_utc, to_local


@dataclass(frozen=True, slots=True)
class PlannedReminder:
    offset_days: int
    scheduled_at: datetime  # UTC


def effective_due(due: date, calendar: WorkCalendar, shift_to_working_day: bool) -> date:
    return calendar.next_working_day(due) if shift_to_working_day else due


def plan(
    *,
    due: date,
    offsets: Sequence[int],
    send_hour: int,
    now: datetime,
) -> list[PlannedReminder]:
    today = to_local(now).date()
    if due < today:
        return []
    out: list[PlannedReminder] = []
    for off in sorted(set(offsets), reverse=True):
        send_day = due - timedelta(days=off)
        if send_day < today:
            continue
        at = local_datetime_utc(send_day, time(send_hour))
        if at < now:  # today, but the hour has passed
            at = now
        out.append(PlannedReminder(off, at))
    return out


def next_occurrence(rule: str, after: date, until: date | None = None, dtstart: date | None = None) -> date | None:
    """Next date of an RRULE strictly after `after`."""
    start = datetime.combine(dtstart or after, time())
    rr = rrulestr(rule, dtstart=start)
    nxt = rr.after(datetime.combine(after, time()), inc=False)
    if nxt is None:
        return None
    d = nxt.date()
    return None if until and d > until else d
