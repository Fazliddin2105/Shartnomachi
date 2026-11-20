from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import ADMIN, API, login, login_privileged


async def test_registration_requires_consent(client: AsyncClient) -> None:
    phone = "+998911110001"
    await client.post(f"{API}/auth/otp", json={"phone": phone})
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "123456"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "consent_required"
    # code was not consumed by the failed consent check
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "123456", "consent": True})
    assert r.status_code == 200 and r.json()["is_new_user"] is True


async def test_invalid_phone_and_code(client: AsyncClient) -> None:
    r = await client.post(f"{API}/auth/otp", json={"phone": "12345"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "phone_invalid"
    phone = "+998911110002"
    await client.post(f"{API}/auth/otp", json={"phone": phone})
    for _ in range(5):
        r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "000000", "consent": True})
        assert r.json()["error"]["code"] == "otp_invalid"
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "123456", "consent": True})
    assert r.json()["error"]["code"] == "otp_locked"


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient) -> None:
    phone = "+998911110003"
    await client.post(f"{API}/auth/otp", json={"phone": phone})
    tokens = (
        await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": "123456", "consent": True})
    ).json()
    r1 = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    # replaying the rotated token revokes the whole family
    r2 = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.json()["error"]["code"] == "refresh_reused"
    r3 = await client.post(f"{API}/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]})
    assert r3.status_code == 401


async def test_me_and_profile_encryption(client: AsyncClient) -> None:
    h = await login(client, "+998911110004")
    r = await client.put(
        f"{API}/me/profile", headers=h, json={"full_name": "Test Foydalanuvchi", "pinfl": "31234567890123"}
    )
    assert r.status_code == 200 and r.json()["has_pinfl"] is True
    me = (await client.get(f"{API}/me", headers=h)).json()
    assert "pinfl" not in me["profile"]  # never echoed back
    r = await client.patch(f"{API}/me", headers=h, json={"channels": ["in_app", "telegram"]})
    assert r.json()["preferences"]["channels"] == ["in_app", "telegram"]


async def test_admin_requires_mfa_and_permission(client: AsyncClient) -> None:
    citizen = await login(client, "+998911110005")
    assert (await client.get(f"{API}/admin/users", headers=citizen)).status_code == 403
    admin = await login_privileged(client, ADMIN)
    r = await client.get(f"{API}/admin/users", headers=admin)
    assert r.status_code == 200 and len(r.json()) >= 5
    v = await client.get(f"{API}/admin/audit/verify", headers=admin)
    assert v.json()["ok"] is True and v.json()["checked"] > 0


async def test_unauthenticated(client: AsyncClient) -> None:
    r = await client.get(f"{API}/me")
    assert r.status_code == 401 and r.json()["error"]["request_id"]
