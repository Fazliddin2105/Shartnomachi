from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutils import utcnow
from app.db.base import Base, UUIDPk
from app.db.types import EncryptedJSON


class MediationRequest(UUIDPk, Base):
    """A request (application) to a mediator prepared by the user — «Mediatsiya to'g'risida»gi Qonun (O'RQ-482).

    The platform only drafts the application (+ the draft agreement on applying mediation, MQ 16) as DOCX;
    the mediator does not work in the system. Form data is personal, so it is stored encrypted.
    """

    __tablename__ = "mediation_requests"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | ready (all required fields filled)
    form: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, default=dict)
    ai_draft: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
