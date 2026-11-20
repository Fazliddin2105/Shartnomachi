"""OneID (sso.egov.uz) OAuth2 client.

Flow: /auth/oneid/authorize -> redirect user -> OneID -> callback with `code`
-> exchange for access token -> fetch identity -> find-or-create user.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable, Unauthorized


@dataclass(frozen=True, slots=True)
class OneIdIdentity:
    subject: str  # PINFL
    full_name: str | None
    phone: str | None
    email: str | None
    tin: str | None


def _require_config() -> None:
    s = get_settings()
    if not (s.oneid_client_id and s.oneid_client_secret and s.oneid_redirect_uri):
        raise IntegrationUnavailable("OneID is not configured")


def authorize_url(state: str) -> str:
    _require_config()
    s = get_settings()
    q = {
        "response_type": "one_code",
        "client_id": s.oneid_client_id,
        "redirect_uri": s.oneid_redirect_uri,
        "scope": s.oneid_client_id,
        "state": state,
    }
    return f"{s.oneid_base_url}?{urlencode(q)}"


async def exchange_code(code: str) -> OneIdIdentity:
    _require_config()
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            s.oneid_base_url,
            data={
                "grant_type": "one_authorization_code",
                "client_id": s.oneid_client_id,
                "client_secret": s.oneid_client_secret,
                "redirect_uri": s.oneid_redirect_uri,
                "code": code,
            },
        )
        if r.is_error or "access_token" not in r.json():
            raise Unauthorized("OneID code exchange failed", code="oneid_failed")
        token = r.json()["access_token"]
        r2 = await client.post(
            s.oneid_base_url,
            data={
                "grant_type": "one_access_token_identify",
                "client_id": s.oneid_client_id,
                "client_secret": s.oneid_client_secret,
                "access_token": token,
                "scope": s.oneid_client_id,
            },
        )
        if r2.is_error:
            raise Unauthorized("OneID identify failed", code="oneid_failed")
        d = r2.json()
    pin = d.get("pin")
    if not pin:
        raise Unauthorized("OneID returned no PINFL", code="oneid_failed")
    return OneIdIdentity(
        subject=str(pin),
        full_name=d.get("full_name"),
        phone=d.get("mob_phone_no"),
        email=d.get("email"),
        tin=d.get("tin"),
    )
