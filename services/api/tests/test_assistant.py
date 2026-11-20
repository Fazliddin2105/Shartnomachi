"""Endpoints the web app needs: situation assistant, dashboard, STIR lookup, autofix, hashes, report download."""

from __future__ import annotations

import io
from datetime import timedelta

from docx import Document
from httpx import AsyncClient

from app.core.timeutils import today_local
from tests.conftest import API, login

RENT = """IJARA SHARTNOMASI
1. Ijaraga beruvchi Toshkent sh., Chilonzor 5 manzilidagi kvartirani Ijarachiga beradi.
2. Ijara haqi oyiga 4 500 000 so'm, har oyning 5-sanasigacha to'lanadi.
3. To'lov kechiktirilsa kuniga 1.5% penya to'lanadi.
4. Ijaraga beruvchi shartnomani 24 soat ichida ogohlantirishsiz bekor qilishi mumkin.
"""


async def test_answers_merge_deeply_and_accept_dotted_keys(client: AsyncClient) -> None:
    h = await login(client, "+998935000001")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "rent_commercial", "my_role": "A"})).json()
    url = f"{API}/contracts/{c['id']}/answers"
    await client.patch(url, headers=h, json={"answers": {"party_a": {"name": "“Toshkent Invest” MChJ"}}})
    await client.patch(url, headers=h, json={"answers": {"party_a.stir": "305891247"}})  # one field at a time
    await client.patch(url, headers=h, json={"answers": {"party_a": {"mfo": "00873"}}})
    got = (await client.get(f"{API}/contracts/{c['id']}", headers=h)).json()["answers"]["party_a"]
    assert got == {"name": "“Toshkent Invest” MChJ", "stir": "305891247", "mfo": "00873"}


async def test_autofix_and_preview_hash_equals_signed_hash(client: AsyncClient) -> None:
    h = await login(client, "+998935000002")
    today = today_local()
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})).json()
    answers = {
        "party_a": {"name": "Aliyev Vali"},
        "party_b": {"name": "Karimov Sardor"},
        "city": "Toshkent",
        "contract_date": today.isoformat(),
        "amount": 10_000_000,
        "currency": "UZS",
        "given_date": today.isoformat(),
        "return_date": (today + timedelta(days=90)).isoformat(),
        "penalty_percent_per_day": 1,
    }
    r = (await client.patch(f"{API}/contracts/{c['id']}/answers", headers=h, json={"answers": answers})).json()
    assert "PENALTY_RATE_HIGH" in {f["rule_code"] for f in r["findings"]}

    fixed = (await client.post(f"{API}/contracts/{c['id']}/autofix", headers=h)).json()
    assert {"field": "penalty_percent_per_day", "value": 0.1} in fixed["applied"]
    assert "PENALTY_RATE_HIGH" not in {f["rule_code"] for f in fixed["findings"]}
    again = (await client.post(f"{API}/contracts/{c['id']}/autofix", headers=h)).json()
    assert again["applied"] == []

    pv = (await client.get(f"{API}/contracts/{c['id']}/preview", headers=h)).json()
    v = (await client.post(f"{API}/contracts/{c['id']}/generate", headers=h, json={})).json()["version"]
    assert pv["content_sha256"] == v["sha256"]  # «the hash you see is the hash you sign»


async def test_scan_gauge_and_report_download(client: AsyncClient) -> None:
    h = await login(client, "+998935000003")
    scan = (await client.post(f"{API}/scans/text", headers=h, json={"text": RENT})).json()
    assert 34 <= scan["risk_percent"] <= 100
    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=h)).json()
    assert rep["overall"]["risk_percent"] == scan["risk_percent"] and rep["overall"]["risk_label"]
    dl = await client.get(f"{API}/scans/{scan['id']}/report/download", headers=h)
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    text = "\n".join(p.text for p in Document(io.BytesIO(dl.content)).paragraphs)
    assert "SHARTNOMA TAHLILI HISOBOTI" in text and "ogohlantirishsiz" in text

    other = await login(client, "+998935000004")
    assert (await client.get(f"{API}/scans/{scan['id']}/report/download", headers=other)).status_code == 404


async def test_dashboard_aggregate(client: AsyncClient) -> None:
    h = await login(client, "+998935000005")
    empty = (await client.get(f"{API}/dashboard", headers=h)).json()
    assert empty["contracts"]["total"] == 0 and empty["last_scan"] is None and empty["invitations"] == 0
    await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})
    await client.post(f"{API}/scans/text", headers=h, json={"text": RENT})
    d = (await client.get(f"{API}/dashboard", headers=h)).json()
    assert d["contracts"]["total"] == 1 and d["contracts"]["counts"]["draft"] == 1
    assert d["contracts"]["recent"][0]["title"] == "Qarz shartnomasi"
    ls = d["last_scan"]
    assert ls["risk_percent"] >= 34 and ls["top_findings"] and ls["contract_type_code"] == "rent_residential"
    assert {"upcoming_30d", "overdue", "unpaid_total"} <= set(d["obligations"])
    assert d["user"]["phone_masked"].endswith("05") and "***" in d["user"]["phone_masked"]


async def test_situation_assistant_rules(client: AsyncClient) -> None:
    h = await login(client, "+998935000006")

    async def ask(text: str) -> dict:
        r = await client.post(f"{API}/assistant/situation", headers=h, json={"text": text})
        assert r.status_code == 200, r.text
        return r.json()

    a = await ask("Kvartiramni bir yilga ijaraga bermoqchiman")
    assert a["contract_type"]["code"] == "rent_residential" and a["action"] == "builder" and a["source"] == "rules"
    b = await ask("Menga noturar bino ijarasi shartnomasini berishdi, imzolashdan oldin tekshirib bering")
    assert b["contract_type"]["code"] == "rent_commercial" and b["action"] == "scanner"
    c = await ask("Do'stimga notarius orqali qarz bermoqchiman")
    assert c["contract_type"]["code"] == "loan_notarial"
    d = await ask("Salom")
    assert d["contract_type"] is None and d["action"] == "consult"


async def test_stir_lookup(client: AsyncClient) -> None:
    h = await login(client, "+998935000007")
    assert (await client.get(f"{API}/lookup/stir/12345", headers=h)).json()["valid"] is False
    nf = (await client.get(f"{API}/lookup/stir/309876543", headers=h)).json()
    assert nf["valid"] is True and nf["found"] is False
    r = await client.post(
        f"{API}/companies",
        headers=h,
        json={
            "name": "Smart Cloud",
            "stir": "309876543",
            "address": "Toshkent",
            "director_name": "Aliyev Sardor",
            "requisites": {"mfo": "00440", "oked": "62010"},
        },
    )
    assert r.status_code == 201, r.text
    other = await login(client, "+998935000008")
    f = (await client.get(f"{API}/lookup/stir/309876543", headers=other)).json()
    assert (
        f["found"] is True and f["name"] == "Smart Cloud" and f["director"] == "Aliyev Sardor" and f["mfo"] == "00440"
    )


async def test_web_sdk_is_served(client: AsyncClient) -> None:
    r = await client.get("/sdk/lexlab-api.js")
    assert r.status_code == 200 and "global.LexLab = LexLab" in r.text
