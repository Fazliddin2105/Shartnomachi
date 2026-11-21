"""AI layer: policy on top of the rule engine, PII masking for external models, scan/contract flows."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.ai import llm
from app.ai import service as ai
from app.core.config import Environment, LLMProvider, Settings, get_settings
from app.db.session import session_scope
from app.modules.notifications.models import Notification
from app.workers import queue
from tests.conftest import API, login

RENT = """IJARA SHARTNOMASI
1. Ijaraga beruvchi Aliyev Vali Karimovich (JShShIR 31234567890123) kvartirani Ijarachiga ijaraga beradi.
2. Ijarachi har oy 3 000 000 so'm to'lashga majbur, birinchi to'lov 05.01.2027 gacha.
3. Ijaraga beruvchi ijara haqini bir tomonlama oshirishga haqli.
4. Ijarachi kvartirada mehmon qabul qilishi uchun Ijaraga beruvchining yozma ruxsatini oladi.
5. Nizolar sud tartibida hal qilinadi."""


class FakeLLM:
    """OpenAI-compatible chat completions emulator; records what was sent."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        self.requests.append(body)
        user = body["messages"][-1]["content"]
        if "Savol:" in user:
            content = {
                "answer": "Ijara haqi har oy to'lanadi ([2]-band). [NAME_1] ijaraga beruvchi.",
                "clause_refs": [1],
                "confidence": 0.8,
                "consult_lawyer": False,
            }
        else:
            content = {
                "summary": "Shartnoma ijarachi uchun noqulay shartlarga ega.",
                "risk_level": "high",
                "issues": [
                    {
                        "clause_index": 3,
                        "severity": "red",
                        "title": "Shaxsiy hayotga aralashuv",
                        "explanation": "Mehmon qabul qilish uchun ruxsat talab qilish ijarachining huquqini cheklaydi.",
                        "law_ref": "Fuqarolik kodeksi",
                        "suggestion": "Bandni olib tashlang.",
                        "confidence": 0.7,
                    },
                    {
                        "clause_index": 2,
                        "severity": "yellow",
                        "title": "Takroriy",
                        "explanation": "qoida bilan bir xil",
                        "confidence": 0.9,
                    },  # clause 2 is already flagged by the rule engine -> must be dropped
                    {
                        "clause_index": 99,
                        "severity": "blue",
                        "title": "Noaniq muddat",
                        "explanation": "Shartnoma muddati ko'rsatilmagan.",
                        "confidence": 0.4,
                    },
                ],
                "obligations": [
                    {
                        "party": "B",
                        "who": "Ijarachi",
                        "title": "Oylik ijara haqini to'lash",
                        "due_date": "2027-01-05",
                        "amount": 3000000,
                        "currency": "UZS",
                        "recurring": "monthly",
                        "clause_index": 1,
                        "confidence": 0.9,
                    },
                ],
                "template_deviations": [],
            }
        return httpx.Response(
            200,
            json={
                "model": "fake-qwen",
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"total_tokens": 10},
            },
        )


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLM]:
    fake = FakeLLM()
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", LLMProvider.OPENAI_COMPATIBLE)
    monkeypatch.setattr(s, "llm_base_url", "http://llm.test/v1")
    monkeypatch.setattr(s, "llm_is_local", False)  # behave like DeepSeek: masking must kick in
    llm.configure_transport(httpx.MockTransport(fake.handler))
    yield fake
    llm.configure_transport(None)


# --- pure policy ---------------------------------------------------------------------------------


def test_policy_downgrades_dedupes_and_validates() -> None:
    data = {
        "risk_level": "nonsense",
        "issues": [
            {"clause_index": 0, "severity": "red", "title": "A", "explanation": "x", "confidence": 1.7},
            {"clause_index": 1, "severity": "yellow", "title": "B", "explanation": "y", "confidence": 0.9},
            {"clause_index": 7, "severity": "weird", "title": "C", "explanation": "z", "confidence": "bad"},
            {"severity": "blue"},
        ],
    }
    r = ai.normalise(data, n_clauses=3, flagged={1})
    assert [i.title for i in r.issues] == ["A", "C"]
    assert r.issues[0].severity == "yellow" and r.issues[0].ai_severity == "red" and r.issues[0].needs_lawyer
    assert r.issues[0].confidence == 1.0 and r.issues[1].clause_index is None and r.issues[1].severity == "blue"
    assert r.risk_level == "medium"


def test_external_llm_forbidden_in_production() -> None:
    with pytest.raises(ValueError, match="External LLM"):
        Settings(
            environment=Environment.PROD,
            jwt_secret="x" * 40,
            master_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            llm_provider=LLMProvider.OPENAI_COMPATIBLE,
            llm_is_local=False,
        )


def test_template_comparison_is_deterministic() -> None:
    tpl = {
        "clauses": [
            {
                "key": "c1",
                "body": "1. Ijaraga beruvchi turar joyni Ijarachiga vaqtincha egalik qilish va foydalanish uchun beradi.",
            },
            {
                "key": "c2",
                "body": "2. Ijarachi turar joydan maqsadiga muvofiq foydalanishi va joriy ta'mirni amalga oshirishi shart.",
            },
            {"key": "c3", "body": "3. Nizolar muzokaralar yo'li bilan, kelishuvga erishilmasa sudda hal qilinadi."},
        ]
    }
    res = ai.compare_with_template(
        [
            "1. Ijaraga beruvchi turar joyni Ijarachiga vaqtincha egalik qilish va foydalanish uchun beradi.",
            "2. Nizolar sud tartibida hal qilinadi.",
        ],
        tpl,
    )
    status = {c["key"]: c["status"] for c in res["clauses"]}
    assert status["c1"] == "ok" and status["c2"] == "missing"
    assert 0 < res["conformity"] < 1


# --- flows ------------------------------------------------------------------------------------------


async def test_scan_ai_review_masks_pii_and_never_blocks(client: AsyncClient, fake_llm: FakeLLM) -> None:
    user = await login(client, "+998981000001")
    r = await client.post(f"{API}/scans/text", headers=user, json={"text": RENT})
    scan = r.json()
    assert scan["ai_status"] == "pending"
    await queue.drain()

    # nothing personal left our server
    sent = json.dumps(fake_llm.requests[0], ensure_ascii=False)
    assert "31234567890123" not in sent and "Aliyev Vali Karimovich" not in sent and "[PINFL_1]" in sent

    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=user)).json()
    assert rep["ai"]["status"] == "done" and rep["ai"]["model"] == "fake-qwen" and rep["ai"]["masked"] is True
    ai_cards = [f for f in rep["red_clauses"] + rep["risky_clauses"] + rep["advice"] if f["source"] == "ai"]
    titles = " ".join(f["explanation"] for f in ai_cards)
    # a confident AI "contrary to law" verdict is shown red in the scanner (analysis only), flagged for a lawyer
    ai_red = [f for f in rep["red_clauses"] if f["source"] == "ai"]
    assert len(ai_red) == 1 and "Shaxsiy hayotga aralashuv" in ai_red[0]["explanation"]
    assert ai_red[0]["needs_lawyer"] and ai_red[0]["suggestion"] == "Bandni olib tashlang."
    assert rep["overall"]["risk_level"] == "high"
    assert "Takroriy" not in titles  # duplicate of a rule finding dropped

    async with session_scope() as db:
        note = await db.scalar(select(Notification).where(Notification.type == "scan.ai_ready"))
        assert note is not None

    # AI obligations become *unconfirmed* reminders
    r = await client.post(f"{API}/scans/{scan['id']}/obligations", headers=user)
    assert len(r.json()["created"]) == 1
    ob = (await client.get(f"{API}/obligations", headers=user)).json()[0]
    assert ob["confirmed"] is False and ob["recurrence_rule"] == "FREQ=MONTHLY" and "Ijarachi" in ob["title"]

    # Q&A: grounded answer, masked tokens restored for the user
    a = (
        await client.post(
            f"{API}/scans/{scan['id']}/ai/ask", headers=user, json={"question": "Ijara qachon to'lanadi?"}
        )
    ).json()
    assert a["clause_refs"] == [1] and "Aliyev Vali Karimovich" in a["answer"]


async def test_ai_disabled_by_default(client: AsyncClient) -> None:
    user = await login(client, "+998981000002")
    scan = (await client.post(f"{API}/scans/text", headers=user, json={"text": RENT})).json()
    assert scan["ai_status"] == "disabled"
    r = await client.post(f"{API}/scans/{scan['id']}/ai/ask", headers=user, json={"question": "Nima?"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled"
