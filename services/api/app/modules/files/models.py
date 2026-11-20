from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutils import utcnow
from app.db.base import Base, UUIDPk


class StoredFile(UUIDPk, Base):
    __tablename__ = "files"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(127))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)  # hash of the *plaintext*
    encrypted: Mapped[bool] = mapped_column(Boolean, default=True)
    wrapped_key: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(32), default="generic")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
