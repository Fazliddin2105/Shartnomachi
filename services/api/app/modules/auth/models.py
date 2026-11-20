from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutils import utcnow
from app.db.base import Base, UUIDPk
from app.db.types import StrEnumType


class OtpPurpose(StrEnum):
    LOGIN = "login"
    APPROVE_CONTRACT = "approve_contract"
    CONFIRM_PHONE = "confirm_phone"


class OtpCode(UUIDPk, Base):
    """One-time codes. Only an HMAC of the code is stored."""

    __tablename__ = "otp_codes"

    phone: Mapped[str] = mapped_column(String(20), index=True)
    purpose: Mapped[OtpPurpose] = mapped_column(StrEnumType(OtpPurpose))
    # Binds the code to a specific action (e.g. contract version id) so a login
    # code can never be replayed to sign a contract and vice versa.
    context_ref: Mapped[str | None] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column()
    consumed_at: Mapped[datetime | None] = mapped_column()
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AuthSession(UUIDPk, Base):
    """A login session backed by a rotating refresh token.

    Rotation: each refresh issues a new token and marks the old one replaced.
    Presenting a replaced token again => token theft => whole family revoked.
    """

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    mfa: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(16), default="otp")
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column()
