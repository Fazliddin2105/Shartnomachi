from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import JSONType, StrEnumType
from app.modules.rules.engine import Scope, Severity


class RuleStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"  # only approved rules are executed
    NEEDS_REVIEW = "needs_review"  # law changed; still executed but flagged
    RETIRED = "retired"


class LegalRule(UUIDPk, Timestamps, Base):
    """One row per (code, version). Editing an approved rule creates a new draft version."""

    __tablename__ = "legal_rules"
    __table_args__ = (UniqueConstraint("code", "version"),)

    code: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # NULL => applies to every contract type
    contract_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contract_types.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[Scope] = mapped_column(StrEnumType(Scope), default=Scope.ANSWERS)
    category: Mapped[str | None] = mapped_column(String(32))
    severity: Mapped[Severity] = mapped_column(StrEnumType(Severity))
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSONType)  # the `when` condition
    message: Mapped[str] = mapped_column(Text)
    fix_suggestion: Mapped[str | None] = mapped_column(Text)
    law_ref: Mapped[str | None] = mapped_column(String(255))
    lex_url: Mapped[str | None] = mapped_column(String(512))
    lex_doc_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    status: Mapped[RuleStatus] = mapped_column(StrEnumType(RuleStatus), default=RuleStatus.DRAFT, index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column()
    approved_by: Mapped[uuid.UUID | None] = mapped_column()
    approved_at: Mapped[datetime | None] = mapped_column()
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
