"""SMS gateways: console (dev) and Eskiz.uz (prod)."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import SmsBackend, get_settings
from app.core.errors import IntegrationUnavailable

log = logging.getLogger(__name__)


class SmsSender(Protocol):
    async def send(self, phone: str, text: str) -> str | None: ...


class ConsoleSms:
    """Prints messages to the log. Never use in production."""

    sent: list[tuple[str, str]]

    def __init__(self) -> None:
        self.sent = []

    async def send(self, phone: str, text: str) -> str | None:
        self.sent.append((phone, text))
        log.warning("SMS[console] -> %s: %s", phone, text)
        return None


class EskizSms:
    """notify.eskiz.uz client with cached bearer token (valid ~30 days)."""

    _TOKEN_TTL = 25 * 24 * 3600

    def __init__(self) -> None:
        s = get_settings()
        if not (s.eskiz_email and s.eskiz_password):
            raise IntegrationUnavailable("Eskiz credentials are not configured")
        self._s = s
        self._token: str | None = None
        self._token_at = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(base_url=s.eskiz_base_url, timeout=10)

    async def _auth(self, force: bool = False) -> str:
        async with self._lock:
            if not force and self._token and time.monotonic() - self._token_at < self._TOKEN_TTL:
                return self._token
            r = await self._client.post(
                "/auth/login", data={"email": self._s.eskiz_email, "password": self._s.eskiz_password}
            )
            r.raise_for_status()
            self._token = r.json()["data"]["token"]
            self._token_at = time.monotonic()
            return self._token

    async def send(self, phone: str, text: str) -> str | None:
        payload = {"mobile_phone": phone.lstrip("+"), "message": text, "from": self._s.eskiz_from}
        for attempt in (1, 2):
            token = await self._auth(force=attempt == 2)
            r = await self._client.post("/message/sms/send", data=payload, headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and attempt == 1:
                continue
            if r.is_error:
                raise IntegrationUnavailable(f"Eskiz error {r.status_code}")
            return str(r.json().get("id"))
        raise IntegrationUnavailable("Eskiz authentication failed")


@lru_cache
def get_sms_sender() -> SmsSender:
    if get_settings().sms_backend == SmsBackend.ESKIZ:
        return EskizSms()
    return ConsoleSms()
