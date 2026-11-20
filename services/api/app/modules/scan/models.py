from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import EncryptedString, JSONType, StrEnumType


class ScanStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"  # OCR sifati past: foydalanuvchi matnni tasdiqlashi kerak
    DONE = "done"
    FAILED = "failed"


class FindingKind(StrEnum):
    ILLEGAL = "illegal"  # qizil band
    RISKY = "risky"  # qaltis band
    ADVICE = "advice"
    DUTY = "duty"  # sizning majburiyatingiz
    RIGHT = "right"  # sizning huquqingiz
    MISSING = "missing"  # yetishmayotgan majburiy element


class Decision(StrEnum):
    AGREE = "agree"
    OBJECT = "object"


class ScanJob(UUIDPk, Timestamps, Base):
    __tablename__ = "scan_jobs"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"))
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    contract_type_code: Mapped[str | None] = mapped_column(String(64))
    type_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    side: Mapped[str | None] = mapped_column(String(8))  # A | B — user's perspective
    status: Mapped[ScanStatus] = mapped_column(StrEnumType(ScanStatus), default=ScanStatus.QUEUED, index=True)
    extraction: Mapped[str | None] = mapped_column(String(16))  # text_layer | ocr | plain
    ocr_text: Mapped[str | None] = mapped_column(EncryptedString)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    text_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    clauses_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str | None] = mapped_column(String(8))  # low | medium | high
    risk_score: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(String(500))
    # AI layer (spec §9): disabled | pending | done | failed; result kept for the report and audits
    ai_status: Mapped[str | None] = mapped_column(String(16))
    ai_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, server_default="{}")
    analyzed_at: Mapped[datetime | None] = mapped_column()


class ScanFinding(UUIDPk, Base):
    __tablename__ = "scan_findings"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True)
    clause_index: Mapped[int | None] = mapped_column(Integer)
    clause_text: Mapped[str | None] = mapped_column(EncryptedString)
    category: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[FindingKind] = mapped_column(StrEnumType(FindingKind))
    source: Mapped[str] = mapped_column(String(16), default="rules", server_default="rules")  # rules|template|ai
    severity: Mapped[str | None] = mapped_column(String(8))  # red | yellow | blue
    rule_code: Mapped[str | None] = mapped_column(String(64))
    law_ref: Mapped[str | None] = mapped_column(String(255))
    explanation: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # amounts, dates, deadlines
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    user_decision: Mapped[Decision | None] = mapped_column(StrEnumType(Decision))
    decided_at: Mapped[datetime | None] = mapped_column()
