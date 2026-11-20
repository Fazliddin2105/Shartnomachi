from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import JSONType, StrEnumType


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


class ContentTask(UUIDPk, Timestamps, Base):
    """Work item for legal editors (e.g. law changed -> review rule / contract template)."""

    __tablename__ = "content_tasks"

    entity: Mapped[str] = mapped_column(String(32))  # legal_rule | contract_type
    entity_id: Mapped[uuid.UUID] = mapped_column(index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(StrEnumType(TaskStatus), default=TaskStatus.OPEN, index=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column()
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class ContentReport(UUIDPk, Timestamps, Base):
    """User complaint about a wrong verdict ("shikoyat qilish"): feeds the rule test-suite (spec §9)."""

    __tablename__ = "content_reports"

    entity: Mapped[str] = mapped_column(String(32))  # legal_rule | scan_finding | contract_type
    entity_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[ReportStatus] = mapped_column(StrEnumType(ReportStatus), default=ReportStatus.OPEN)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
