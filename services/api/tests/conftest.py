from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="lexlab-test-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
        "STORAGE_LOCAL_ROOT": str(_TMP / "storage"),
        "SCHEDULER_MODE": "off",
        "OTP_DEV_FIXED_CODE": "123456",
        "SMS_BACKEND": "console",
        "OTP_RESEND_COOLDOWN_SECONDS": "0",
        "OTP_HOURLY_LIMIT": "1000",
        "EIMZO_SERVER_URL": "http://eimzo.internal:8080",
        "EIMZO_SITE_HOST": "lexlab.test",
        # never call a real LLM from tests (services/api/.env may hold a real key)
        "LLM_PROVIDER": "none",
        "LLM_API_KEY": "",
        "LLM_IS_LOCAL": "true",
        "FRONTEND_DIR": "",
    }
)

import pyotp  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.ratelimit import get_limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, init_engine  # noqa: E402
from app.integrations.sms import get_sms_sender  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import run as seed_run  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    init_engine()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_run(dev_users=True)
    yield
    await dispose_engine()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    lim = get_limiter()
    if hasattr(lim, "reset"):
        lim.reset()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def sms_outbox() -> list[tuple[str, str]]:
    return get_sms_sender().sent  # type: ignore[attr-defined, no-any-return]


async def login(client: AsyncClient, phone: str) -> dict[str, str]:
    r = await client.post(f"{API}/auth/otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "123456", "consent": True})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    if body.get("mfa_required"):
        raise AssertionError("use login_privileged for MFA users")
    return {"Authorization": f"Bearer {body['access_token']}"}


_totp_secrets: dict[str, str] = {}


async def login_privileged(client: AsyncClient, phone: str) -> dict[str, str]:
    """Editors/admins need TOTP: enrol once, then log in with OTP + TOTP."""
    if phone not in _totp_secrets:
        headers = await login(client, phone)
        r = await client.post(f"{API}/auth/2fa/setup", headers=headers)
        secret = r.json()["secret"]
        r = await client.post(f"{API}/auth/2fa/enable", headers=headers, json={"code": pyotp.TOTP(secret).now()})
        assert r.status_code == 204, r.text
        _totp_secrets[phone] = secret
    await client.post(f"{API}/auth/otp", json={"phone": phone})
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "123456"})
    assert r.json().get("mfa_required"), r.text
    r = await client.post(
        f"{API}/auth/2fa/verify",
        json={"mfa_token": r.json()["mfa_token"], "code": pyotp.TOTP(_totp_secrets[phone]).now()},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


ADMIN, EDITOR1, EDITOR2, LAWYER, MODERATOR = (
    "+998900000001",
    "+998900000002",
    "+998900000003",
    "+998900000004",
    "+998900000005",
)
