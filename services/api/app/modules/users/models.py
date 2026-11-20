from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import EncryptedString, JSONType, StrEnumType


class UserRole(StrEnum):
    CITIZEN = "citizen"
    BUSINESS = "business"  # MChJ / YaTT vakili
    LAWYER = "lawyer"
    EDITOR = "editor"  # kontent-muharrir (huquqiy ekspert)
    MODERATOR = "moderator"
    ADMIN = "admin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    DELETION_REQUESTED = "deletion_requested"
    DELETED = "deleted"


class ProfileType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    LAWYER = "lawyer"


class CompanyRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    role: Mapped[UserRole] = mapped_column(StrEnumType(UserRole), default=UserRole.CITIZEN)
    status: Mapped[UserStatus] = mapped_column(StrEnumType(UserStatus), default=UserStatus.ACTIVE)
    locale: Mapped[str] = mapped_column(String(5), default="uz")
    # Notification preferences, e.g. {"channels": ["in_app", "sms", "telegram"]}
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))
    totp_secret: Mapped[str | None] = mapped_column(EncryptedString)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # HMAC of a PINFL proven by government infrastructure (OneID or an E-IMZO signature).
    # Self-declared profile data never sets this: it is the only key used to find an
    # account from a certificate, so nobody can hijack an account by typing someone's PINFL.
    verified_pinfl_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    identity_verified_via: Mapped[str | None] = mapped_column(String(16))  # oneid | eimzo
    identity_verified_at: Mapped[datetime | None] = mapped_column()
    consent_at: Mapped[datetime | None] = mapped_column()
    last_login_at: Mapped[datetime | None] = mapped_column()
    deleted_at: Mapped[datetime | None] = mapped_column()

    profile: Mapped[Profile | None] = relationship(
        back_populates="user", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )


class Profile(UUIDPk, Timestamps, Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    type: Mapped[ProfileType] = mapped_column(StrEnumType(ProfileType), default=ProfileType.PERSON)
    full_name: Mapped[str | None] = mapped_column(String(255))
    pinfl: Mapped[str | None] = mapped_column(EncryptedString)  # JShShIR, encrypted at rest
    pinfl_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # HMAC for lookups
    passport: Mapped[str | None] = mapped_column(EncryptedString)
    tin: Mapped[str | None] = mapped_column(String(9), index=True)  # STIR
    license_no: Mapped[str | None] = mapped_column(String(64))
    license_verified_at: Mapped[datetime | None] = mapped_column()
    region: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(EncryptedString)

    user: Mapped[User] = relationship(back_populates="profile")


class Company(UUIDPk, Timestamps, Base):
    __tablename__ = "companies"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    legal_form: Mapped[str] = mapped_column(String(32), default="MChJ")
    stir: Mapped[str] = mapped_column(String(9), unique=True)
    address: Mapped[str | None] = mapped_column(String(512))
    director_name: Mapped[str | None] = mapped_column(String(255))
    # {"bank": "...", "account": "...", "mfo": "...", "oked": "..."}
    requisites: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    members: Mapped[list[CompanyMember]] = relationship(
        back_populates="company", lazy="selectin", cascade="all, delete-orphan"
    )


class CompanyMember(Base):
    __tablename__ = "company_members"
    __table_args__ = (UniqueConstraint("company_id", "user_id"),)

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[CompanyRole] = mapped_column(StrEnumType(CompanyRole), default=CompanyRole.MEMBER)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company] = relationship(back_populates="members")
