from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import EncryptedString, JSONType, StrEnumType


class CaseStatus(StrEnum):
    OPEN = "open"
    DISPUTE = "dispute"  # nizo rejimi
    CLOSED = "closed"


class AttachmentType(StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    SCAN = "scan"
    AUDIO = "audio"
    DOCUMENT = "document"


class CaseFile(UUIDPk, Timestamps, Base):
    __tablename__ = "case_files"

    lawyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    client_name: Mapped[str | None] = mapped_column(EncryptedString)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[CaseStatus] = mapped_column(StrEnumType(CaseStatus), default=CaseStatus.OPEN, index=True)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Attorney-client privilege: private to the lawyer unless explicitly shared.
    shared_with_client: Mapped[bool] = mapped_column(Boolean, default=False)

    steps: Mapped[list[CaseStep]] = relationship(
        order_by="CaseStep.step_at", cascade="all, delete-orphan", lazy="selectin"
    )


class CaseStep(UUIDPk, Base):
    __tablename__ = "case_steps"

    case_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_files.id", ondelete="CASCADE"), index=True)
    step_at: Mapped[datetime] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(EncryptedString)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    obligation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("obligations.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    attachments: Mapped[list[CaseAttachment]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class CaseAttachment(UUIDPk, Base):
    __tablename__ = "case_attachments"

    step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_steps.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"))
    type: Mapped[AttachmentType] = mapped_column(StrEnumType(AttachmentType))
    sha256: Mapped[str] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(default=utcnow)  # server time stamp
    note: Mapped[str | None] = mapped_column(String(500))
