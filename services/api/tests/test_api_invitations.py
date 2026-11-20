"""Two-party flow without the SMS token: the invitee logs in with the invited phone and sees the invitation."""

from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient

from app.core.timeutils import today_local
from tests.conftest import API, login

A_PHONE, B_PHONE, STRANGER = "+998932000001", "+998932000002", "+998932000003"


def _rent_answers() -> dict:
    today = today_local()
    return {
        "party_a": {"name": "Aliyev Vali", "pinfl": "31234567890123"},
        "party_b": {"name": "Karimov Sardor", "pinfl": "31234567890124"},
        "city": "Toshkent",
        "contract_date": today.isoformat(),
        "property_address": "Toshkent sh., Chilonzor tumani, 5-uy",
        "rent_amount": 4_500_000,
        "payment_day": 5,
        "start_date": (today + timedelta(days=1)).isoformat(),
        "utilities_paid_by": "tenant",
        "notice_days": 30,
        "penalty_percent_per_day": 0.1,
    }


async def _generated_contract(client: AsyncClient, a: dict) -> tuple[str, str]:
    c = (
        await client.post(f"{API}/contracts", headers=a, json={"type_code": "rent_residential", "my_role": "A"})
    ).json()
    r = await client.patch(f"{API}/contracts/{c['id']}/answers", headers=a, json={"answers": _rent_answers()})
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/contracts/{c['id']}/generate", headers=a, json={"language": "uz"})
    assert r.status_code == 200, r.text
    return c["id"], r.json()["version"]["sha256"]


async def _unread_types(client: AsyncClient, h: dict) -> list[str]:
    return [n["type"] for n in (await client.get(f"{API}/notifications", headers=h)).json()["items"]]


async def test_invitation_list_accept_and_activate(client: AsyncClient) -> None:
    a = await login(client, A_PHONE)
    b = await login(client, B_PHONE)  # registered before the invite -> also gets an in-app notification
    stranger = await login(client, STRANGER)
    cid, sha = await _generated_contract(client, a)

    assert (
        await client.post(f"{API}/contracts/{cid}/invite", headers=a, json={"phone": B_PHONE, "role": "B"})
    ).status_code == 200
    assert "contract.invited" in await _unread_types(client, b)

    # Only the invited phone sees the invitation
    assert (await client.get(f"{API}/contracts/invitations", headers=stranger)).json() == []
    inv = (await client.get(f"{API}/contracts/invitations", headers=b)).json()
    assert len(inv) == 1
    item = inv[0]
    assert item["contract_id"] == cid and item["role"] == "B" and item["current_sha256"] == sha
    assert item["inviter_name"] and item["total_amount"] == "4500000.00"

    # The invitee can read the text before joining; strangers can't
    pv = await client.get(f"{API}/contracts/invitations/{item['party_id']}/preview", headers=b)
    assert pv.status_code == 200 and "Chilonzor" in str(pv.json()["sections"])
    r = await client.get(f"{API}/contracts/invitations/{item['party_id']}/preview", headers=stranger)
    assert r.json()["error"]["code"] == "invite_phone_mismatch"
    r = await client.post(f"{API}/contracts/invitations/{item['party_id']}/accept", headers=stranger)
    assert r.json()["error"]["code"] == "invite_phone_mismatch"

    r = await client.post(f"{API}/contracts/invitations/{item['party_id']}/accept", headers=b)
    assert r.status_code == 200, r.text
    assert (await client.get(f"{API}/contracts/invitations", headers=b)).json() == []
    assert "contract.joined" in await _unread_types(client, a)
    # Used invitation can't be reused
    r = await client.post(f"{API}/contracts/invitations/{item['party_id']}/accept", headers=b)
    assert r.json()["error"]["code"] == "invite_invalid"

    # Both sides approve the same hash -> active, both notified
    for h in (a, b):
        assert (await client.post(f"{API}/contracts/{cid}/approve/otp", headers=h)).status_code == 200
        r = await client.post(
            f"{API}/contracts/{cid}/approve", headers=h, json={"method": "otp", "code": "123456", "sha256": sha}
        )
        assert r.status_code == 200, r.text
    assert r.json()["contract_status"] == "active"
    assert "contract.approved_by_party" in await _unread_types(client, b)
    for h in (a, b):
        assert "contract.activated" in await _unread_types(client, h)


async def test_invitation_decline(client: AsyncClient) -> None:
    a = await login(client, "+998932000011")
    cid, _ = await _generated_contract(client, a)
    b_phone = "+998932000012"
    await client.post(f"{API}/contracts/{cid}/invite", headers=a, json={"phone": b_phone, "role": "B"})
    b = await login(client, b_phone)  # registers after the invite: the list still finds it
    inv = (await client.get(f"{API}/contracts/invitations", headers=b)).json()
    assert [x["contract_id"] for x in inv] == [cid]

    assert (
        await client.post(f"{API}/contracts/invitations/{inv[0]['party_id']}/decline", headers=b)
    ).status_code == 204
    assert (await client.get(f"{API}/contracts/invitations", headers=b)).json() == []
    assert "contract.invite_declined" in await _unread_types(client, a)
    r = await client.post(f"{API}/contracts/invitations/{inv[0]['party_id']}/accept", headers=b)
    assert r.json()["error"]["code"] == "invite_invalid"
