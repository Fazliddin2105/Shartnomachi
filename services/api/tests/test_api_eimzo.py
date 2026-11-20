from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.timeutils import today_local
from app.integrations import eimzo
from tests.conftest import API, login, sms_outbox
from tests.fake_eimzo import FakeEimzoServer, decode, fake_sign


@pytest.fixture
def server() -> Iterator[FakeEimzoServer]:
    fake = FakeEimzoServer()
    eimzo.configure_transport(fake.transport())
    yield fake
    eimzo.configure_transport(None)


async def _signed_challenge(client: AsyncClient, **key: str) -> str:
    r = await client.get(f"{API}/auth/eimzo/challenge")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    return fake_sign(r.json()["challenge"].encode(), **key)  # type: ignore[arg-type]


# --- parsing -------------------------------------------------------------------------------


def test_x500_parsing_with_escaped_comma() -> None:
    subject = eimzo.parse_x500(
        "CN=OOO \\, TEST,UID=400000001,1.2.860.3.16.1.2=31234567890123,1.2.860.3.16.1.1=301234567"
    )
    ident = eimzo.CertificateIdentity.from_json({"subjectName": subject, "validTo": "2027-01-01 00:00:00"})
    assert ident.common_name == "OOO , TEST" and ident.pinfl == "31234567890123"
    assert ident.person_tin == "400000001" and ident.legal_tin == "301234567" and ident.is_legal_entity
    assert ident.valid_to is not None and ident.valid_to.isoformat() == "2026-12-31T19:00:00+00:00"  # Tashkent -> UTC


# --- login -----------------------------------------------------------------------------------


async def test_eimzo_login_register_and_relogin(client: AsyncClient, server: FakeEimzoServer) -> None:
    key = {"pinfl": "31111111111111", "cn": "ALIYEV VALI"}
    pkcs7 = await _signed_challenge(client, **key)
    r = await client.post(f"{API}/auth/eimzo", json={"pkcs7": pkcs7, "consent": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_new_user"] is True
    me = (await client.get(f"{API}/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})).json()
    assert me["identity_verified_via"] == "eimzo" and me["phone"] is None
    assert me["profile"]["full_name"] == "ALIYEV VALI" and me["profile"]["has_pinfl"]

    # challenge is single-use
    r = await client.post(f"{API}/auth/eimzo", json={"pkcs7": pkcs7})
    assert r.status_code == 401 and r.json()["error"]["code"] == "eimzo_challenge_expired"

    # second login finds the same account
    r = await client.post(f"{API}/auth/eimzo", json={"pkcs7": await _signed_challenge(client, **key)})
    assert r.json()["is_new_user"] is False

    # revoked certificate is rejected with a precise error
    r = await client.post(
        f"{API}/auth/eimzo", json={"pkcs7": await _signed_challenge(client, pinfl="32222222222222", revoked="1")}
    )
    assert r.json()["error"]["code"] == "eimzo_certificate_invalid"


async def test_self_declared_pinfl_cannot_hijack_account(client: AsyncClient, server: FakeEimzoServer) -> None:
    attacker = await login(client, "+998951000001")
    victim_pinfl = "33333333333333"
    # attacker types the victim's PINFL into their own profile ...
    await client.put(f"{API}/me/profile", headers=attacker, json={"pinfl": victim_pinfl})
    # ... the victim logs in with their real key and gets a *separate* new account
    r = await client.post(
        f"{API}/auth/eimzo", json={"pkcs7": await _signed_challenge(client, pinfl=victim_pinfl), "consent": True}
    )
    assert r.json()["is_new_user"] is True
    # and the attacker can no longer bind that identity
    r = await client.post(
        f"{API}/auth/eimzo/link", headers=attacker, json={"pkcs7": await _signed_challenge(client, pinfl=victim_pinfl)}
    )
    assert r.json()["error"]["code"] == "identity_taken"


async def test_link_eimzo_to_phone_account(client: AsyncClient, server: FakeEimzoServer) -> None:
    h = await login(client, "+998951000002")
    r = await client.post(
        f"{API}/auth/eimzo/link", headers=h, json={"pkcs7": await _signed_challenge(client, pinfl="34444444444444")}
    )
    assert r.status_code == 204
    assert (await client.get(f"{API}/me", headers=h)).json()["identity_verified_via"] == "eimzo"
    # E-IMZO login now lands in the phone account
    r = await client.post(f"{API}/auth/eimzo", json={"pkcs7": await _signed_challenge(client, pinfl="34444444444444")})
    assert r.json()["is_new_user"] is False


async def test_unconfigured_server(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "eimzo_server_url", None)
    r = await client.get(f"{API}/auth/eimzo/challenge")
    assert r.status_code == 503 and r.json()["error"]["code"] == "eimzo_unavailable"


# --- contract signing ----------------------------------------------------------------------------


async def _pending_contract(client: AsyncClient, a: dict, b: dict, b_phone: str, company_id: str | None = None) -> str:
    c = (
        await client.post(
            f"{API}/contracts", headers=a, json={"type_code": "loan", "my_role": "A", "company_id": company_id}
        )
    ).json()
    today = today_local()
    await client.patch(
        f"{API}/contracts/{c['id']}/answers",
        headers=a,
        json={
            "answers": {
                "party_a": {"name": "A"},
                "party_b": {"name": "B"},
                "city": "Toshkent",
                "contract_date": today.isoformat(),
                "amount": 5_000_000,
                "currency": "UZS",
                "given_date": today.isoformat(),
                "return_date": (today + timedelta(days=30)).isoformat(),
            }
        },
    )
    assert (await client.post(f"{API}/contracts/{c['id']}/generate", headers=a, json={})).status_code == 200
    await client.post(f"{API}/contracts/{c['id']}/invite", headers=a, json={"phone": b_phone, "role": "B"})
    token = re.search(r"Taklif kodi: (\S+)", sms_outbox()[-1][1]).group(1)  # type: ignore[union-attr]
    assert (
        await client.post(f"{API}/contracts/invitations/accept", headers=b, json={"token": token})
    ).status_code == 200
    return str(c["id"])


async def test_contract_signed_by_both_parties_with_eimzo(client: AsyncClient, server: FakeEimzoServer) -> None:
    a, b = await login(client, "+998951000011"), await login(client, "+998951000012")
    cid = await _pending_contract(client, a, b, "+998951000012")

    payload = (await client.get(f"{API}/contracts/{cid}/approve/eimzo", headers=a)).json()
    doc = base64.b64decode(payload["document_b64"])
    assert payload["content_sha256"] in doc.decode()

    async def approve(h: dict, pkcs7: str) -> dict:
        r = await client.post(
            f"{API}/contracts/{cid}/approve",
            headers=h,
            json={"method": "eimzo", "pkcs7": pkcs7, "sha256": payload["content_sha256"]},
        )
        return r.json()

    r = await approve(a, fake_sign(doc, pinfl="35555555555555", cn="PARTY A"))
    assert r["approved"] and r["legal_strength"] == "qualified_signature" and r["pending_parties"] == ["B"]

    # B tries to sign a different document (tampered bytes) -> rejected
    r = await approve(b, fake_sign(doc.replace(b'"version":1', b'"version":9'), pinfl="36666666666666"))
    assert r["error"]["code"] == "eimzo_document_mismatch"
    # B tries to sign with A's key -> rejected (A's identity is now bound to A's account)
    r = await approve(b, fake_sign(doc, pinfl="35555555555555"))
    assert r["error"]["code"] == "eimzo_signer_mismatch"

    r = await approve(b, fake_sign(doc, pinfl="36666666666666", cn="PARTY B"))
    assert r["contract_status"] == "active"

    content = (await client.get(f"{API}/contracts/{cid}/versions/1/content", headers=b)).json()
    signers = {x["signer"]["signer_name"]: x["signer"] for x in content["approvals"]}
    assert set(signers) == {"PARTY A", "PARTY B"}
    assert signers["PARTY A"]["signer_pinfl"] == "355*******5555" and signers["PARTY A"]["timestamp_time"]
    assert content["signed_container_available"] is True

    p7s = await client.get(f"{API}/contracts/{cid}/versions/1/signature.p7s", headers=a)
    container = decode(base64.b64encode(p7s.content).decode())
    assert [s["cn"] for s in container["signers"]] == ["PARTY A", "PARTY B"]
    assert all(path != "/backend/auth" for path, _ in server.calls)  # signing used verify, not auth


async def test_company_party_requires_company_key(client: AsyncClient, server: FakeEimzoServer) -> None:
    a, b = await login(client, "+998951000021"), await login(client, "+998951000022")
    company = (await client.post(f"{API}/companies", headers=a, json={"name": "Test MChJ", "stir": "301234567"})).json()
    cid = await _pending_contract(client, a, b, "+998951000022", company_id=company["id"])
    payload = (await client.get(f"{API}/contracts/{cid}/approve/eimzo", headers=a)).json()
    doc = base64.b64decode(payload["document_b64"])

    body = {"method": "eimzo", "sha256": payload["content_sha256"]}
    r = await client.post(
        f"{API}/contracts/{cid}/approve", headers=a, json={**body, "pkcs7": fake_sign(doc, pinfl="37777777777777")}
    )  # personal key
    assert r.json()["error"]["code"] == "eimzo_company_mismatch"
    r = await client.post(
        f"{API}/contracts/{cid}/approve",
        headers=a,
        json={**body, "pkcs7": fake_sign(doc, pinfl="37777777777777", legal_tin="301234567")},
    )
    assert r.status_code == 200 and r.json()["pending_parties"] == ["B"]
