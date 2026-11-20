from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import StrEnumType


class ObligationKind(StrEnum):
    DUTY = "duty"  # majburiyat
    RIGHT = "right"  # huquq


class ObligationStatus(StrEnum):
    PENDING = "pending"  # kutilmoqda
    REMINDED = "reminded"  # eslatildi
    DONE = "done"  # bajarildi
    OVERDUE = "overdue"  # kechikdi
    CANCELLED = "cancelled"  # bekor qilindi


class ObligationSource(StrEnum):
    CONTRACT = "contract"
    SCAN = "scan"
    MANUAL = "manual"


class Obligation(UUIDPk, Timestamps, Base):
    __tablename__ = "obligations"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_parties.id", ondelete="SET NULL"))
    source: Mapped[ObligationSource] = mapped_column(StrEnumType(ObligationSource), default=ObligationSource.MANUAL)
    kind: Mapped[ObligationKind] = mapped_column(StrEnumType(ObligationKind), default=ObligationKind.DUTY)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    due_date: Mapped[date] = mapped_column(Date, index=True)  # local (Asia/Tashkent) date
    shift_to_working_day: Mapped[bool] = mapped_column(Boolean, default=True)
    # RFC 5545 RRULE, e.g. "FREQ=MONTHLY;BYMONTHDAY=10" (doimiy majburiyat)
    recurrence_rule: Mapped[str | None] = mapped_column(String(255))
    recurrence_until: Mapped[date | None] = mapped_column(Date)
    series_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # all occurrences share it
    occurrence_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ObligationStatus] = mapped_column(
        StrEnumType(ObligationStatus), default=ObligationStatus.PENDING, index=True
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)  # AI-extracted => False until user confirms
    completed_at: Mapped[datetime | None] = mapped_column()
    proof_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    source_clause_ref: Mapped[str | None] = mapped_column(String(64))


class ReminderStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Reminder(UUIDPk, Base):
    __tablename__ = "reminders"

    obligation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("obligations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    offset_days: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16))
    scheduled_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[ReminderStatus] = mapped_column(
        StrEnumType(ReminderStatus), default=ReminderStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column()
    sent_at: Mapped[datetime | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(String(500))
