from __future__ import annotations

import re
import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.timeutils import today_local
from app.db.session import session_scope
from app.modules.obligations.models import Obligation, Reminder
from tests.conftest import API, login, sms_outbox

A_PHONE, B_PHONE, STRANGER = "+998931000001", "+998931000002", "+998931000003"


def _answers(given: str, ret: str) -> dict:
    return {
        "party_a": {"name": "Aliyev Vali", "pinfl": "31234567890123", "address": "Toshkent"},
        "party_b": {"name": "Karimov Sardor", "address": "Guliston"},
        "city": "Toshkent",
        "contract_date": given,
        "amount": 20_000_000,
        "currency": "UZS",
        "given_date": given,
        "return_date": ret,
        "penalty_percent_per_day": 1,
    }


async def test_full_contract_lifecycle(client: AsyncClient) -> None:
    a = await login(client, A_PHONE)
    b = await login(client, B_PHONE)
    stranger = await login(client, STRANGER)

    types = (await client.get(f"{API}/contract-types")).json()
    assert {t["code"] for t in types} >= {"loan", "labor", "rent_residential", "services", "sale"}
    detail = (await client.get(f"{API}/contract-types/loan")).json()
    assert detail["questionnaire"]["sections"] and detail["library"]

    c = (await client.post(f"{API}/contracts", headers=a, json={"type_code": "loan", "my_role": "A"})).json()
    cid = c["id"]

    # Real-time validation: return date before given date is illegal (red), penalty 1%/day risky (yellow)
    today = today_local()
    r = await client.patch(
        f"{API}/contracts/{cid}/answers",
        headers=a,
        json={"answers": _answers(today.isoformat(), (today - timedelta(days=1)).isoformat())},
    )
    report = r.json()
    codes = {f["rule_code"]: f["severity"] for f in report["findings"]}
    assert codes["LOAN_RETURN_BEFORE_GIVEN"] == "red" and codes["PENALTY_RATE_HIGH"] == "yellow"
    assert report["summary"]["blocking"] is True

    # Generation is blocked while red findings exist
    r = await client.post(f"{API}/contracts/{cid}/generate", headers=a, json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "illegal_clauses"

    # Fix and add a library clause
    lib = {x["code"]: x["id"] for x in detail["library"]}
    ret = today + timedelta(days=4)
    r = await client.patch(
        f"{API}/contracts/{cid}/answers",
        headers=a,
        json={
            "answers": {"return_date": ret.isoformat(), "penalty_percent_per_day": 0.1},
            "selected_clauses": [{"clause_id": lib["force_majeure"], "params": {"notice_days": 3}}],
        },
    )
    assert r.json()["summary"]["blocking"] is False

    r = await client.post(f"{API}/contracts/{cid}/generate", headers=a, json={"language": "uz"})
    assert r.status_code == 200, r.text
    version = r.json()["version"]
    assert len(version["sha256"]) == 64

    content = (await client.get(f"{API}/contracts/{cid}/versions/1/content", headers=a)).json()
    texts = " ".join(s["text"] for s in content["content"]["sections"])
    assert "20 000 000 UZS" in texts and "3 kun ichida" in texts
    assert (await client.get(f"{API}/contracts/{cid}/versions/1/verify", headers=a)).json()["intact"] is True
    dl = await client.get(f"{API}/contracts/{cid}/versions/1/download?format=docx", headers=a)
    assert dl.status_code == 200 and dl.content[:2] == b"PK" and dl.headers["x-content-sha256"] == version["sha256"]

    # Row-level security: strangers can't even see that the contract exists
    assert (await client.get(f"{API}/contracts/{cid}", headers=stranger)).status_code == 404

    # Invite party B; token only travels by SMS
    r = await client.post(f"{API}/contracts/{cid}/invite", headers=a, json={"phone": B_PHONE, "role": "B"})
    assert r.status_code == 200 and "token" not in r.json()
    token = re.search(r"Taklif kodi: (\S+)", sms_outbox()[-1][1]).group(1)  # type: ignore[union-attr]
    # wrong user can't use B's invitation
    r = await client.post(f"{API}/contracts/invitations/accept", headers=stranger, json={"token": token})
    assert r.json()["error"]["code"] == "invite_phone_mismatch"
    assert (
        await client.post(f"{API}/contracts/invitations/accept", headers=b, json={"token": token})
    ).status_code == 200

    # Approval binds to the hash the user saw
    r = await client.post(f"{API}/contracts/{cid}/approve", headers=a, json={"code": "123456", "sha256": "0" * 64})
    assert r.json()["error"]["code"] == "version_mismatch"
    for h in (a, b):
        assert (await client.post(f"{API}/contracts/{cid}/approve/otp", headers=h)).status_code == 200
        r = await client.post(
            f"{API}/contracts/{cid}/approve",
            headers=h,
            json={"method": "otp", "code": "123456", "sha256": version["sha256"]},
        )
        assert r.status_code == 200, r.text
    assert r.json()["contract_status"] == "active" and r.json()["pending_parties"] == []

    # Obligations were derived for each party, with reminders
    obs_b = (await client.get(f"{API}/obligations?contract_id={cid}", headers=b)).json()
    assert [o["title"] for o in obs_b] == ["Qarzni qaytarish"] and obs_b[0]["amount"] == "20000000.00"
    obs_a = (await client.get(f"{API}/obligations?contract_id={cid}", headers=a)).json()
    assert obs_a[0]["kind"] == "right"
    async with session_scope() as db:
        rem = (
            await db.scalars(select(Reminder).join(Obligation).where(Obligation.contract_id == uuid.UUID(cid)))
        ).all()
        assert {r.offset_days for r in rem} <= {6, 3, 2, 1, 0} and rem

    # Any edit after activation is forbidden
    r = await client.patch(f"{API}/contracts/{cid}/answers", headers=a, json={"answers": {"amount": 1}})
    assert r.json()["error"]["code"] == "contract_locked"
    listed = (await client.get(f"{API}/contracts?tab=active", headers=b)).json()
    assert any(x["id"] == cid for x in listed)


async def test_form_requirement_for_real_estate(client: AsyncClient) -> None:
    a = await login(client, "+998931000010")
    c = (await client.post(f"{API}/contracts", headers=a, json={"type_code": "sale", "my_role": "A"})).json()
    r = await client.patch(
        f"{API}/contracts/{c['id']}/answers", headers=a, json={"answers": {"object_type": "real_estate"}}
    )
    form = r.json()["form"]
    assert form["requirement"] == "registration" and "almashtirmaydi" in form["warning"]
    assert "price" in r.json()["missing_fields"]
    r = await client.post(f"{API}/contracts/{c['id']}/generate", headers=a, json={})
    assert r.json()["error"]["code"] == "answers_incomplete"


async def test_labor_rules(client: AsyncClient) -> None:
    a = await login(client, "+998931000011")
    c = (await client.post(f"{API}/contracts", headers=a, json={"type_code": "labor", "my_role": "A"})).json()
    r = await client.patch(
        f"{API}/contracts/{c['id']}/answers",
        headers=a,
        json={
            "answers": {"probation_months": 6, "weekly_hours": 48, "annual_leave_days": 15, "contract_kind": "fixed"}
        },
    )
    reds = {f["rule_code"] for f in r.json()["findings"] if f["severity"] == "red"}
    assert reds == {
        "LABOR_PROBATION_MAX",
        "LABOR_WEEKLY_HOURS_MAX",
        "LABOR_ANNUAL_LEAVE_MIN",
        "LABOR_FIXED_TERM_NO_END",
    }
