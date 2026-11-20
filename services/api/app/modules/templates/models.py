from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import JSONType, StrEnumType


class TemplateStatus(StrEnum):
    DRAFT = "draft"  # imported / edited, waiting for a second expert
    APPROVED = "approved"  # applied to the contract type (current)
    SUPERSEDED = "superseded"  # an older approved version
    REJECTED = "rejected"


class TemplateVersion(UUIDPk, Timestamps, Base):
    """A versioned contract template, typically imported from an official lex.uz model form.

    `source` keeps provenance so templates can be audited and re-checked against lex.uz:
    {"kind": "lexuz", "doc_id", "lang", "url", "annex", "annex_title", "document_title",
     "edition_date", "in_force_from", "annex_sha256", "element_ids", "fetched_at", "script"}
    """

    __tablename__ = "contract_template_versions"
    __table_args__ = (UniqueConstraint("contract_type_code", "version"),)

    contract_type_code: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[TemplateStatus] = mapped_column(
        StrEnumType(TemplateStatus), default=TemplateStatus.DRAFT, index=True
    )
    title_uz: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    questionnaire: Mapped[dict[str, Any]] = mapped_column(JSONType)
    template: Mapped[dict[str, Any]] = mapped_column(JSONType)
    template_ru: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    source: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    original_text: Mapped[str | None] = mapped_column(Text)  # the official form text, verbatim
    report: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    author_id: Mapped[uuid.UUID | None] = mapped_column()
    approved_by: Mapped[uuid.UUID | None] = mapped_column()
    approved_at: Mapped[datetime | None] = mapped_column()
    review_note: Mapped[str | None] = mapped_column(Text)
