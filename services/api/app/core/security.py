"""JWT access tokens. Refresh tokens are opaque and stored hashed (see auth module)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.errors import Unauthorized


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    session_id: uuid.UUID
    mfa: bool


def create_access_token(*, user_id: uuid.UUID, role: str, session_id: uuid.UUID, mfa: bool = False) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = timedelta(minutes=s.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "sid": str(session_id),
        "mfa": mfa,
        "iss": s.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), int(ttl.total_seconds())


def decode_access_token(token: str) -> TokenClaims:
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
            issuer=s.jwt_issuer,
            options={"require": ["exp", "sub", "iss", "sid"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("Access token expired", code="token_expired") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("Invalid access token", code="token_invalid") from e
    if payload.get("typ") != "access":
        raise Unauthorized("Invalid token type", code="token_invalid")
    return TokenClaims(
        user_id=uuid.UUID(payload["sub"]),
        role=payload["role"],
        session_id=uuid.UUID(payload["sid"]),
        mfa=bool(payload.get("mfa")),
    )
