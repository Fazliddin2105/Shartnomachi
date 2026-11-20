"""OTP issuing and verification (shared by login and contract approval)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import get_client
from app.core.crypto import constant_time_equals, hmac_sha256, random_digits
from app.core.errors import RateLimited, Unauthorized, ValidationFailed
from app.core.ratelimit import get_limiter
from app.core.timeutils import ensure_utc, utcnow
from app.integrations.sms import get_sms_sender
from app.modules.auth.models import OtpCode, OtpPurpose

_PHONE_RE = re.compile(r"^\+998\d{9}$")

_SMS_TEXT = {
    OtpPurpose.LOGIN: "LexLab: kirish kodi {code}. Kodni hech kimga bermang.",
    OtpPurpose.APPROVE_CONTRACT: "LexLab: shartnomani tasdiqlash kodi {code}. Hujjat: {ref}. Kodni hech kimga bermang.",
    OtpPurpose.CONFIRM_PHONE: "LexLab: telefonni tasdiqlash kodi {code}.",
}


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        digits = "998" + digits
    phone = "+" + digits
    if not _PHONE_RE.match(phone):
        raise ValidationFailed("Phone must be a valid Uzbekistan number (+998XXXXXXXXX)", code="phone_invalid")
    return phone


@dataclass(frozen=True, slots=True)
class OtpIssued:
    expires_in: int
    resend_in: int


def _hash(phone: str, purpose: OtpPurpose, context_ref: str | None, code: str) -> str:
    return hmac_sha256(f"{phone}|{purpose.value}|{context_ref or ''}|{code}", purpose="otp")


async def issue(db: AsyncSession, *, phone: str, purpose: OtpPurpose, context_ref: str | None = None) -> OtpIssued:
    s = get_settings()
    now = utcnow()
    client = get_client()
    if client.ip:
        await get_limiter().hit(f"otp-ip:{client.ip}", limit=s.otp_ip_hourly_limit, window_s=3600)

    last = await db.scalar(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.purpose == purpose)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if last is not None:
        elapsed = (now - ensure_utc(last.created_at)).total_seconds()
        if elapsed < s.otp_resend_cooldown_seconds:
            raise RateLimited(
                "Please wait before requesting a new code",
                code="otp_cooldown",
                details={"retry_after_s": int(s.otp_resend_cooldown_seconds - elapsed)},
            )
    hourly = await db.scalar(
        select(func.count(OtpCode.id)).where(OtpCode.phone == phone, OtpCode.created_at >= now - timedelta(hours=1))
    )
    if (hourly or 0) >= s.otp_hourly_limit:
        raise RateLimited("Too many codes requested for this number", code="otp_hourly_limit")

    code = s.otp_dev_fixed_code if (s.is_dev and s.otp_dev_fixed_code) else random_digits(s.otp_length)
    db.add(
        OtpCode(
            phone=phone,
            purpose=purpose,
            context_ref=context_ref,
            code_hash=_hash(phone, purpose, context_ref, code),
            expires_at=now + timedelta(seconds=s.otp_ttl_seconds),
            ip=client.ip,
            created_at=now,
        )
    )
    await db.flush()
    await get_sms_sender().send(phone, _SMS_TEXT[purpose].format(code=code, ref=(context_ref or "")[:8]))
    return OtpIssued(expires_in=s.otp_ttl_seconds, resend_in=s.otp_resend_cooldown_seconds)


async def verify(
    db: AsyncSession,
    *,
    phone: str,
    code: str,
    purpose: OtpPurpose,
    context_ref: str | None = None,
) -> OtpCode:
    """Verify and consume the latest active code. Wrong attempts are counted."""
    s = get_settings()
    now = utcnow()
    otp = await db.scalar(
        select(OtpCode)
        .where(
            OtpCode.phone == phone,
            OtpCode.purpose == purpose,
            OtpCode.consumed_at.is_(None),
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if otp is None or ensure_utc(otp.expires_at) < now:
        raise Unauthorized("Code expired or not requested", code="otp_expired")
    if otp.attempts >= s.otp_max_attempts:
        raise Unauthorized("Too many wrong attempts; request a new code", code="otp_locked")
    if (otp.context_ref or None) != (context_ref or None) or not constant_time_equals(
        otp.code_hash, _hash(phone, purpose, context_ref, code.strip())
    ):
        otp.attempts += 1
        await db.flush()
        # Commit the attempt counter even though the request will fail.
        await db.commit()
        raise Unauthorized("Invalid code", code="otp_invalid")
    otp.consumed_at = now
    await db.flush()
    return otp
