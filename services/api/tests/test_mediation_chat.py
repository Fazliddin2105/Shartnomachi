"""«Shartnomachi AI» chat and mediator applications (O'RQ-482). A fake LLM is used — no real model is called."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterator

import httpx
import pytest
from docx import Document
from httpx import AsyncClient

from app.ai import llm
from app.core.config import LLMProvider, get_settings
from tests.conftest import API, login


class FakeLLM:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        self.prompts.append((system, user))
        given = re.findall(r"\[((?:FK|MK|MQ|IHHQ) \d+)-modda", user)
        if "Shartnomachi AI" in system:
            content = {
                "answer": f"Bu holatda {given[0] if given else 'FK 544'}-modda qo'llanadi. Mediatsiyani taklif qiling.",
                "law_refs": [*given[:1], "FK 1"],  # FK 1 is not in the prompt -> dropped
                "action": {"type": "mediation", "type_code": None},
                "confidence": 0.8,
            }
        else:
            content = {
                "subject": "Ijara haqi bo'yicha kelishmovchilik",
                "statement": "Ikkinchi tomon 2 oylik ijara haqini to'lamagan. MQ 29-moddaga ko'ra mediativ kelishuv mumkin.",
                "claims": ["Qarzni 30 kun ichida to'lash"],
                "options": ["Qarzni 2 qismda to'lash", "Penyadan voz kechish evaziga darhol to'lash"],
                "law_refs": ["MQ 29", "MQ 999"],
                "confidence": 0.8,
            }
        return httpx.Response(
            200, json={"model": "fake", "choices": [{"message": {"content": json.dumps(content)}}], "usage": {}}
        )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLM]:
    f = FakeLLM()
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", LLMProvider.OPENAI_COMPATIBLE)
    monkeypatch.setattr(s, "llm_base_url", "http://llm.test/v1")
    llm.configure_transport(httpx.MockTransport(f.handler))
    yield f
    llm.configure_transport(None)


async def _contract(client: AsyncClient, h: dict[str, str]) -> str:
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "rent_private", "my_role": "A"})).json()
    r = await client.patch(
        f"{API}/contracts/{c['id']}/answers",
        headers=h,
        json={
            "answers": {
                "party_a": {"name": "Karimov Abdullo", "address": "Toshkent"},
                "party_b": {"name": "Aliyev Sardor", "address": "Samarqand"},
                "rent_amount": 3000000,
            }
        },
    )
    assert r.status_code == 200, r.text
    return c["id"]


async def test_chat_grounded_in_laws_and_contract(client: AsyncClient, fake: FakeLLM) -> None:
    h = await login(client, "+998981300001")
    cid = await _contract(client, h)
    r = await client.post(
        f"{API}/assistant/chat",
        headers=h,
        json={
            "messages": [
                {"role": "user", "content": "Ijarachi ijara haqini to'lamayapti"},
                {"role": "assistant", "content": "Qancha muddatdan beri?"},
                {"role": "user", "content": "Ikki oy. Nizoni qanday hal qilsam bo'ladi?"},
            ],
            "contract_id": cid,
            "page": "contracts",
        },
    )
    assert r.status_code == 200, r.text
    a = r.json()
    system, prompt = fake.prompts[-1]
    assert "Shartnomachi AI" in system
    assert "Oldingi suhbat" in prompt and "Foydalanuvchining shartnomasi" in prompt and "lex.uz" in prompt
    assert "[MQ 29-modda." in prompt  # a dispute question brings in the mediation law
    assert a["action"] == {"type": "mediation", "type_code": None, "label": "Mediatorga ariza tayyorlash"}
    assert a["law_refs"] and all(x["ref"] != "FK 1-modda" for x in a["law_refs"])
    assert a["law_refs"][0]["url"].startswith("https://lex.uz")

    other = await login(client, "+998981300002")
    r = await client.post(
        f"{API}/assistant/chat",
        headers=other,
        json={"messages": [{"role": "user", "content": "?"}], "contract_id": cid},
    )
    assert r.status_code in (403, 404)  # someone else's contract is never given to the AI
    r = await client.post(
        f"{API}/assistant/chat", headers=h, json={"messages": [{"role": "assistant", "content": "x"}]}
    )
    assert r.status_code == 422


async def test_chat_disabled_without_ai(client: AsyncClient) -> None:
    h = await login(client, "+998981300003")
    r = await client.post(f"{API}/assistant/chat", headers=h, json={"messages": [{"role": "user", "content": "Salom"}]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled"


async def test_mediation_request_flow(client: AsyncClient, fake: FakeLLM) -> None:
    h = await login(client, "+998981300004")
    cid = await _contract(client, h)
    r = await client.post(f"{API}/mediation/requests", headers=h, json={"contract_id": cid})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["form"]["applicant_name"] == "Karimov Abdullo" and m["form"]["respondent_name"] == "Aliyev Sardor"
    assert m["status"] == "draft" and "Nizo mazmuni" in m["missing"]

    r = await client.get(f"{API}/mediation/requests/{m['id']}/docx", headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "mediation_incomplete"
    r = await client.post(f"{API}/mediation/requests/{m['id']}/ai", headers=h)
    assert r.status_code == 422  # AI needs the user's description first

    m = (
        await client.patch(
            f"{API}/mediation/requests/{m['id']}",
            headers=h,
            json={
                "description": "Ijarachi 2026-yil sentabr va oktabr oylari uchun ijara haqini to'lamadi.",
                "claims": "Qarzni to'lash\nShartnomani davom ettirish",
                "mediator_name": "Rasulov Botir",
            },
        )
    ).json()
    assert m["status"] == "ready" and m["missing"] == []

    d = (await client.post(f"{API}/mediation/requests/{m['id']}/ai", headers=h)).json()
    assert d["options"] and [x["ref"] for x in d["law_refs"]] == ["MQ 29-modda"]  # MQ 999 dropped
    assert "Mediatsiya" in fake.prompts[-1][0] and "[MQ 23-modda." in fake.prompts[-1][1]

    r = await client.get(f"{API}/mediation/requests/{m['id']}/docx", headers=h)
    assert r.status_code == 200 and "mediatorga_ariza" in r.headers["content-disposition"]
    text = "\n".join(p.text for p in Document(io.BytesIO(r.content)).paragraphs)
    for s in (
        "MEDIATORGA ARIZA",
        "Karimov Abdullo",
        "Aliyev Sardor",
        "Rasulov Botir",
        "O'RQ-482",
        "MEDIATSIYANI QO'LLASH TO'G'RISIDAGI KELISHUV",
        "Qarzni to'lash",
    ):
        assert s in text, s

    listed = (await client.get(f"{API}/mediation/requests", headers=h)).json()
    assert [x["id"] for x in listed] == [m["id"]] and listed[0]["contract_title"]
    other = await login(client, "+998981300005")
    assert (await client.get(f"{API}/mediation/requests/{m['id']}", headers=other)).status_code == 404
    assert (await client.post(f"{API}/mediation/requests", headers=other, json={"contract_id": cid})).status_code in (
        403,
        404,
    )
    assert (await client.delete(f"{API}/mediation/requests/{m['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/mediation/requests", headers=h)).json() == []


async def test_mediation_without_contract(client: AsyncClient) -> None:
    h = await login(client, "+998981300006")
    r = await client.post(
        f"{API}/mediation/requests",
        headers=h,
        json={
            "applicant_name": "Valiyev Olim",
            "respondent_name": "Do'kon MChJ",
            "subject": "Sifatsiz tovar",
            "description": "Sotib olingan muzlatgich 3 kunda ishdan chiqdi, almashtirish rad etildi.",
        },
    )
    assert r.status_code == 201 and r.json()["status"] == "ready" and r.json()["contract_id"] is None
