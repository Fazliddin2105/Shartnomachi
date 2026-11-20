from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import get_client
from app.core.crypto import hmac_sha256, random_token
from app.core.errors import Conflict, Forbidden, Unauthorized, ValidationFailed
from app.core.security import create_access_token
from app.core.timeutils import ensure_utc, utcnow
from app.integrations import eimzo, oneid
from app.modules.audit import service as audit
from app.modules.auth import otp as otp_service
from app.modules.auth.models import AuthSession, OtpPurpose
from app.modules.auth.schemas import MfaChallenge, TokenPair
from app.modules.users.models import Profile, User, UserRole, UserStatus


def _refresh_hash(token: str) -> str:
    return hmac_sha256(token, purpose="refresh")


async def _issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    method: str,
    mfa: bool,
    family_id: uuid.UUID | None = None,
    is_new_user: bool = False,
) -> tuple[TokenPair, AuthSession]:
    s = get_settings()
    client = get_client()
    refresh = random_token(48)
    session = AuthSession(
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=_refresh_hash(refresh),
        mfa=mfa,
        method=method,
        ip=client.ip,
        user_agent=(client.user_agent or "")[:255] or None,
        expires_at=utcnow() + timedelta(days=s.refresh_token_ttl_days),
    )
    db.add(session)
    await db.flush()
    access, ttl = create_access_token(user_id=user.id, role=user.role.value, session_id=session.id, mfa=mfa)
    return (
        TokenPair(access_token=access, refresh_token=refresh, expires_in=ttl, is_new_user=is_new_user),
        session,
    )


def _mfa_token(user_id: uuid.UUID, method: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "typ": "mfa",
            "mth": method,
            "iss": s.jwt_issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )


async def _complete_login(
    db: AsyncSession, user: User, *, method: str, is_new: bool, strong: bool = False
) -> TokenPair | MfaChallenge:
    """`strong` = the method itself is two-factor (E-IMZO: key file/token + password), so TOTP is skipped."""
    if user.status in (UserStatus.BLOCKED, UserStatus.DELETED):
        raise Forbidden("Account is blocked", code="account_blocked")
    if user.totp_enabled and not strong:
        await audit.record(db, action="auth.mfa_challenge", entity="user", entity_id=user.id, actor_id=user.id)
        return MfaChallenge(mfa_token=_mfa_token(user.id, method))
    user.last_login_at = utcnow()
    pair, session = await _issue_tokens(db, user, method=method, mfa=strong, is_new_user=is_new)
    await audit.record(
        db,
        action="auth.login",
        entity="user",
        entity_id=user.id,
        actor_id=user.id,
        meta={"method": method, "session_id": str(session.id), "mfa": strong},
    )
    return pair


async def request_otp(db: AsyncSession, phone_raw: str) -> otp_service.OtpIssued:
    phone = otp_service.normalize_phone(phone_raw)
    return await otp_service.issue(db, phone=phone, purpose=OtpPurpose.LOGIN)


async def login_with_otp(db: AsyncSession, *, phone_raw: str, code: str, consent: bool) -> TokenPair | MfaChallenge:
    phone = otp_service.normalize_phone(phone_raw)
    user = await db.scalar(select(User).where(User.phone == phone))
    if user is None and not consent:
        # Check consent *before* consuming the code so the user can retry.
        raise ValidationFailed("Personal data processing consent is required to register", code="consent_required")
    await otp_service.verify(db, phone=phone, code=code, purpose=OtpPurpose.LOGIN)
    is_new = False
    if user is None:
        user = User(phone=phone, role=UserRole.CITIZEN, consent_at=utcnow())
        user.profile = Profile()
        db.add(user)
        await db.flush()
        is_new = True
        await audit.record(
            db, action="user.register", entity="user", entity_id=user.id, actor_id=user.id, meta={"method": "otp"}
        )
    return await _complete_login(db, user, method="otp", is_new=is_new)


async def verify_mfa(db: AsyncSession, *, mfa_token: str, code: str) -> TokenPair:
    s = get_settings()
    try:
        payload = jwt.decode(mfa_token, s.jwt_secret, algorithms=[s.jwt_algorithm], issuer=s.jwt_issuer)
    except jwt.PyJWTError as e:
        raise Unauthorized("Invalid MFA token", code="mfa_token_invalid") from e
    if payload.get("typ") != "mfa":
        raise Unauthorized("Invalid MFA token", code="mfa_token_invalid")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.totp_enabled or not user.totp_secret:
        raise Unauthorized("MFA not enabled", code="mfa_token_invalid")
    if not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        await audit.record(db, action="auth.mfa_failed", entity="user", entity_id=user.id, actor_id=user.id)
        await db.commit()
        raise Unauthorized("Invalid 2FA code", code="totp_invalid")
    user.last_login_at = utcnow()
    pair, session = await _issue_tokens(db, user, method=payload.get("mth", "otp"), mfa=True)
    await audit.record(
        db,
        action="auth.login",
        entity="user",
        entity_id=user.id,
        actor_id=user.id,
        meta={"method": payload.get("mth"), "mfa": True, "session_id": str(session.id)},
    )
    return pair


async def refresh(db: AsyncSession, refresh_token: str) -> TokenPair:
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == _refresh_hash(refresh_token)))
    if session is None:
        raise Unauthorized("Invalid refresh token", code="refresh_invalid")
    now = utcnow()
    if session.replaced_by_id is not None or session.revoked_at is not None:
        # Reuse of a rotated token: assume theft, revoke the entire family.
        await db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == session.family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await audit.record(
            db,
            action="auth.refresh_reuse",
            entity="user",
            entity_id=session.user_id,
            actor_id=session.user_id,
            meta={"family_id": str(session.family_id)},
        )
        await db.commit()
        raise Unauthorized("Refresh token reuse detected; please log in again", code="refresh_reused")
    if ensure_utc(session.expires_at) < now:
        raise Unauthorized("Refresh token expired", code="refresh_expired")
    user = await db.get(User, session.user_id)
    if user is None or user.status in (UserStatus.BLOCKED, UserStatus.DELETED):
        raise Unauthorized("Account is not active", code="account_inactive")
    pair, new_session = await _issue_tokens(
        db, user, method=session.method, mfa=session.mfa, family_id=session.family_id
    )
    session.replaced_by_id = new_session.id
    session.revoked_at = now
    return pair


async def logout(db: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID, all_devices: bool) -> None:
    now = utcnow()
    stmt = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if not all_devices:
        current = await db.get(AuthSession, session_id)
        if current is None:
            return
        stmt = stmt.where(AuthSession.family_id == current.family_id)
    await db.execute(stmt.values(revoked_at=now))
    await audit.record(
        db, action="auth.logout", entity="user", entity_id=user_id, actor_id=user_id, meta={"all_devices": all_devices}
    )


# --- TOTP 2FA -----------------------------------------------------------------


async def totp_setup(db: AsyncSession, user: User) -> tuple[str, str]:
    if user.totp_enabled:
        raise ValidationFailed("2FA is already enabled", code="mfa_already_enabled")
    secret = pyotp.random_base32()
    user.totp_secret = secret
    await db.flush()
    label = user.phone or user.email or str(user.id)
    uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=get_settings().totp_issuer)
    return secret, uri


async def totp_enable(db: AsyncSession, user: User, code: str) -> None:
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        raise ValidationFailed("Invalid 2FA code", code="totp_invalid")
    user.totp_enabled = True
    await audit.record(db, action="auth.mfa_enabled", entity="user", entity_id=user.id, actor_id=user.id)


# --- OneID --------------------------------------------------------------------


def oneid_start() -> tuple[str, str]:
    s = get_settings()
    state = jwt.encode(
        {
            "typ": "oneid_state",
            "nonce": random_token(16),
            "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )
    return oneid.authorize_url(state), state


async def oneid_callback(db: AsyncSession, *, code: str, state: str) -> TokenPair | MfaChallenge:
    s = get_settings()
    try:
        st = jwt.decode(state, s.jwt_secret, algorithms=[s.jwt_algorithm])
        if st.get("typ") != "oneid_state":
            raise jwt.InvalidTokenError
    except jwt.PyJWTError as e:
        raise Unauthorized("Invalid OAuth state", code="oauth_state_invalid") from e

    ident = await oneid.exchange_code(code)
    subject_hash = hmac_sha256(ident.subject, purpose="pinfl")
    user = await db.scalar(select(User).where(User.verified_pinfl_hash == subject_hash))
    is_new = False
    if user is None and ident.phone:
        phone = otp_service.normalize_phone(ident.phone)
        user = await db.scalar(select(User).where(User.phone == phone))
        if user is not None:
            mark_identity_verified(user, pinfl=ident.subject, via="oneid", full_name=ident.full_name)
    if user is None:
        user = User(
            phone=otp_service.normalize_phone(ident.phone) if ident.phone else None,
            consent_at=utcnow(),
        )
        user.profile = Profile(tin=ident.tin)
        mark_identity_verified(user, pinfl=ident.subject, via="oneid", full_name=ident.full_name)
        db.add(user)
        await db.flush()
        is_new = True
        await audit.record(
            db, action="user.register", entity="user", entity_id=user.id, actor_id=user.id, meta={"method": "oneid"}
        )
    return await _complete_login(db, user, method="oneid", is_new=is_new)


# --- verified identity (OneID / E-IMZO) ------------------------------------------------


def pinfl_hash(pinfl: str) -> str:
    return hmac_sha256(pinfl, purpose="pinfl")


def mark_identity_verified(
    user: User, *, pinfl: str, via: str, full_name: str | None = None, tin: str | None = None
) -> None:
    """Bind a government-proven PINFL to the account and overwrite self-declared profile data."""
    user.verified_pinfl_hash = pinfl_hash(pinfl)
    user.identity_verified_via, user.identity_verified_at = via, utcnow()
    if user.profile is None:
        user.profile = Profile()
    user.profile.pinfl, user.profile.pinfl_hash = pinfl, pinfl_hash(pinfl)
    if full_name:
        user.profile.full_name = full_name
    if tin:
        user.profile.tin = tin


# --- E-IMZO -------------------------------------------------------------------------------


async def eimzo_challenge() -> tuple[str, int]:
    return await eimzo.EimzoClient().challenge()


async def eimzo_login(db: AsyncSession, *, pkcs7: str, consent: bool) -> TokenPair | MfaChallenge:
    """Login with a signed challenge (doc 0.1 sequence). The challenge is single-use on the server."""
    ident = await eimzo.EimzoClient().authenticate(pkcs7)
    assert ident.pinfl is not None
    user = await db.scalar(select(User).where(User.verified_pinfl_hash == pinfl_hash(ident.pinfl)))
    is_new = False
    if user is None:
        if not consent:
            raise ValidationFailed("Personal data processing consent is required to register", code="consent_required")
        user = User(role=UserRole.CITIZEN, consent_at=utcnow())
        mark_identity_verified(user, pinfl=ident.pinfl, via="eimzo", full_name=ident.common_name, tin=ident.person_tin)
        db.add(user)
        await db.flush()
        is_new = True
        await audit.record(
            db,
            action="user.register",
            entity="user",
            entity_id=user.id,
            actor_id=user.id,
            meta={"method": "eimzo", "cert_serial": ident.serial_number},
        )
    elif user.identity_verified_via != "eimzo" or user.identity_verified_at is None:
        user.identity_verified_via, user.identity_verified_at = "eimzo", utcnow()
    return await _complete_login(db, user, method="eimzo", is_new=is_new, strong=True)


async def eimzo_link(db: AsyncSession, user: User, *, pkcs7: str) -> User:
    """Attach an E-IMZO identity to an existing (e.g. phone) account."""
    ident = await eimzo.EimzoClient().authenticate(pkcs7)
    assert ident.pinfl is not None
    h = pinfl_hash(ident.pinfl)
    if user.verified_pinfl_hash and user.verified_pinfl_hash != h:
        raise Conflict("This account is already bound to another person", code="identity_mismatch")
    owner = await db.scalar(select(User.id).where(User.verified_pinfl_hash == h, User.id != user.id))
    if owner is not None:
        raise Conflict("This E-IMZO identity is already bound to another account", code="identity_taken")
    mark_identity_verified(user, pinfl=ident.pinfl, via="eimzo", full_name=ident.common_name, tin=ident.person_tin)
    await audit.record(
        db,
        action="identity.verified",
        entity="user",
        entity_id=user.id,
        actor_id=user.id,
        meta={"via": "eimzo", "cert_serial": ident.serial_number},
    )
    return user
