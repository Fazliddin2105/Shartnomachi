"""Time helpers. All persisted timestamps are UTC; business dates use Asia/Tashkent.

Working-day arithmetic is pure: callers pass the production calendar
(holidays and transferred working days) loaded from the `calendar_days` table.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import get_settings


@lru_cache
def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def utcnow() -> datetime:
    return datetime.now(UTC)


def today_local() -> date:
    return datetime.now(local_tz()).date()


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(local_tz())


def ensure_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo; normalise any naive datetime as UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def local_datetime_utc(d: date, at: time) -> datetime:
    """A wall-clock time on a local date, converted to UTC."""
    return datetime.combine(d, at, tzinfo=local_tz()).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WorkCalendar:
    holidays: frozenset[date] = field(default_factory=frozenset)
    extra_working_days: frozenset[date] = field(default_factory=frozenset)
    work_week: frozenset[int] = frozenset({0, 1, 2, 3, 4})

    @classmethod
    def build(
        cls,
        holidays: Collection[date] = (),
        extra_working_days: Collection[date] = (),
        work_week: Collection[int] | None = None,
    ) -> WorkCalendar:
        ww = work_week if work_week is not None else get_settings().work_week_days
        return cls(frozenset(holidays), frozenset(extra_working_days), frozenset(ww))

    def is_working_day(self, d: date) -> bool:
        if d in self.extra_working_days:
            return True
        if d in self.holidays:
            return False
        return d.weekday() in self.work_week

    def next_working_day(self, d: date) -> date:
        """`d` itself if it is a working day, otherwise the next one."""
        guard = 0
        while not self.is_working_day(d):
            d += timedelta(days=1)
            guard += 1
            if guard > 366:
                raise ValueError("Calendar has no working days")
        return d

    def add_working_days(self, start: date, days: int) -> date:
        """Counting starts the day *after* `start` (civil-law convention)."""
        if days < 0:
            raise ValueError("days must be >= 0")
        d = start
        remaining = days
        while remaining > 0:
            d += timedelta(days=1)
            if self.is_working_day(d):
                remaining -= 1
        return d

    def add_calendar_days(self, start: date, days: int, *, shift_to_working: bool = True) -> date:
        """Calendar-day term; if it ends on a non-working day it moves to the next working day."""
        end = start + timedelta(days=days)
        return self.next_working_day(end) if shift_to_working else end

    def working_days_between(self, start: date, end: date) -> int:
        if end < start:
            return -self.working_days_between(end, start)
        return sum(1 for i in range(1, (end - start).days + 1) if self.is_working_day(start + timedelta(days=i)))
