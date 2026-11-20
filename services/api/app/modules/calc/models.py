from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk
from app.db.types import StrEnumType


class DayKind(StrEnum):
    HOLIDAY = "holiday"  # bayram / dam olish kuni (ish kunidan ko'chirilgan)
    WORKING = "working"  # dam olish kunidan ko'chirilgan ish kuni


class CalendarDay(Base):
    """Production calendar (Asia/Tashkent): holidays and transferred days."""

    __tablename__ = "calendar_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[DayKind] = mapped_column(StrEnumType(DayKind))
    title: Mapped[str | None] = mapped_column(String(255))


class BhmRate(UUIDPk, Base):
    """Bazaviy hisoblash miqdori (base calculation amount), UZS."""

    __tablename__ = "bhm_rates"

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    valid_from: Mapped[date] = mapped_column(Date, unique=True)
    legal_ref: Mapped[str | None] = mapped_column(String(255))
