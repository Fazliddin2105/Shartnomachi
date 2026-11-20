from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.auth.models import OtpPurpose


class OtpRequest(BaseModel):
    phone: str = Field(examples=["+998901234567"])
    purpose: OtpPurpose = OtpPurpose.LOGIN


class OtpRequested(BaseModel):
    expires_in: int
    resend_in: int


class OtpLogin(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)
    consent: bool = Field(
        default=False, description="Shaxsiy ma'lumotlarni qayta ishlashga rozilik (yangi foydalanuvchi uchun majburiy)"
    )


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    is_new_user: bool = False


class MfaChallenge(BaseModel):
    mfa_required: bool = True
    mfa_token: str


class MfaVerify(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str


class TotpSetup(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCode(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class OneIdAuthorize(BaseModel):
    url: str
    state: str


class OneIdCallback(BaseModel):
    code: str
    state: str


class EimzoChallenge(BaseModel):
    challenge: str = Field(description="E-IMZO ilovasida imzolanadigan matn (bir martalik)")
    ttl: int = Field(description="Amal qilish muddati, soniya")


class EimzoLogin(BaseModel):
    pkcs7: str = Field(min_length=100, max_length=200_000, description="Challenge imzolangan PKCS#7 (Base64)")
    consent: bool = Field(default=False, description="Yangi foydalanuvchi uchun shaxsiy ma'lumotlarga rozilik")


class EimzoLink(BaseModel):
    pkcs7: str = Field(min_length=100, max_length=200_000)
