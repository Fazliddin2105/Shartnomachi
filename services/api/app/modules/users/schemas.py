from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.users.models import CompanyRole, ProfileType, UserRole, UserStatus


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProfileOut(ORM):
    type: ProfileType
    full_name: str | None
    tin: str | None
    license_no: str | None
    license_verified_at: datetime | None
    region: str | None
    has_pinfl: bool = False


class UserOut(ORM):
    id: uuid.UUID
    phone: str | None
    email: str | None
    role: UserRole
    status: UserStatus
    locale: str
    preferences: dict[str, Any]
    totp_enabled: bool
    identity_verified_via: str | None = None
    identity_verified_at: datetime | None = None
    created_at: datetime
    profile: ProfileOut | None


NOTIFICATION_CHANNELS = {"in_app", "push", "sms", "telegram", "email"}


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    locale: str | None = Field(default=None, pattern="^(uz|uz-Cyrl|ru)$")
    channels: list[str] | None = None
    telegram_chat_id: str | None = None

    @field_validator("channels")
    @classmethod
    def _channels(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            bad = set(v) - NOTIFICATION_CHANNELS
            if bad:
                raise ValueError(f"Unknown channels: {sorted(bad)}")
            if not v:
                raise ValueError("At least one channel is required")
        return v


class ProfileUpdate(BaseModel):
    type: ProfileType | None = None
    full_name: str | None = Field(default=None, max_length=255)
    pinfl: str | None = Field(default=None, pattern=r"^\d{14}$")
    passport: str | None = Field(default=None, pattern=r"^[A-Z]{2}\d{7}$")
    tin: str | None = Field(default=None, pattern=r"^\d{9}$")
    license_no: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=512)


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    legal_form: str = Field(default="MChJ", max_length=32)
    stir: str = Field(pattern=r"^\d{9}$")
    address: str | None = None
    director_name: str | None = None
    requisites: dict[str, str] = Field(default_factory=dict)

    @field_validator("requisites")
    @classmethod
    def _req(cls, v: dict[str, str]) -> dict[str, str]:
        allowed = {"bank", "account", "mfo", "oked"}
        if set(v) - allowed:
            raise ValueError(f"Allowed requisites keys: {sorted(allowed)}")
        if "account" in v and not re.fullmatch(r"\d{20}", v["account"]):
            raise ValueError("Bank account must be 20 digits")
        return v


class CompanyMemberOut(ORM):
    user_id: uuid.UUID
    role: CompanyRole
    created_at: datetime


class CompanyOut(ORM):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    legal_form: str
    stir: str
    address: str | None
    director_name: str | None
    requisites: dict[str, Any]
    members: list[CompanyMemberOut]


class MemberAdd(BaseModel):
    phone: str
    role: CompanyRole = CompanyRole.MEMBER


class AdminUserUpdate(BaseModel):
    role: UserRole | None = None
    status: UserStatus | None = None
