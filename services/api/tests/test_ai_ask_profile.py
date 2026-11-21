"""AI Q&A grounded in lex.uz articles (only given articles may be cited) and profile name validation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

import httpx
import pytest
from httpx import AsyncClient

from app.ai import llm
from app.core.config import LLMProvider, get_settings
from app.modules.laws import corpus
from tests.conftest import API, login


class AskLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][-1]["content"]
        self.prompts.append(user)
        given = re.search(r"\[(FK|MK) (\d+)-modda", user)
        cited = f"{given.group(1)} {given.group(2)}" if given else "FK 544"
        content = {
            "answer": f"Shartnomaning [1]-bandida to'lov tartibi bor. Qonun bo'yicha {cited}-modda qo'llanadi.",
            "clause_refs": [1, 99],
            "law_refs": [cited, "FK 1"],  # FK 1 was not given to the model -> must be dropped
            "confidence": 0.8,
            "consult_lawyer": False,
        }
        return httpx.Response(
            200, json={"model": "fake", "choices": [{"message": {"content": json.dumps(content)}}], "usage": {}}
        )


@pytest.fixture
def ask_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[AskLLM]:
    fake = AskLLM()
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", LLMProvider.OPENAI_COMPATIBLE)
    monkeypatch.setattr(s, "llm_base_url", "http://llm.test/v1")
    llm.configure_transport(httpx.MockTransport(fake.handler))
    yield fake
    llm.configure_transport(None)


def test_related_articles_for_questions() -> None:
    nums = [(a["short"], a["number"]) for a in corpus.related("Qarz foizi qancha bo'ladi?", codes=["fk2"])]
    assert ("FK", "734") in nums
    nums = [a["number"] for a in corpus.related("Ijarachi ijara haqini to'lamasa nima bo'ladi?")]
    assert "544" in nums
    assert corpus.related("qanday qachon nima") == []  # only stop-words


async def test_contract_ask_uses_laws_and_filters_refs(client: AsyncClient, ask_llm: AskLLM) -> None:
    h = await login(client, "+998981100001")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "rent_private", "my_role": "A"})).json()
    r = await client.post(
        f"{API}/contracts/{c['id']}/ai/ask", headers=h, json={"question": "Ijara haqini to'lamasa nima bo'ladi?"}
    )
    assert r.status_code == 200, r.text
    a = r.json()
    prompt = ask_llm.prompts[-1]
    assert "Shartnoma turi:" in prompt and "lex.uz" in prompt and "-modda." in prompt
    assert [x["index"] for x in a["clauses"]] == [1] and a["clause_refs"] == [1]
    assert len(a["law_refs"]) == 1 and a["law_refs"][0]["url"].startswith("https://lex.uz")
    assert a["law_refs"][0]["ref"] != "FK 1-modda"


async def test_profile_full_name_validation(client: AsyncClient) -> None:
    h = await login(client, "+998981100002")
    for bad in ["Ali", "12345 Vali", "Aliyev", "Aliyev <b>Vali</b>"]:
        r = await client.put(f"{API}/me/profile", headers=h, json={"full_name": bad})
        assert r.status_code == 422, bad
    r = await client.put(f"{API}/me/profile", headers=h, json={"full_name": "  G'ofurov   Ali  Vali o'g'li "})
    assert r.status_code == 200 and r.json()["full_name"] == "G'ofurov Ali Vali o'g'li"
    me = (await client.get(f"{API}/me", headers=h)).json()
    assert me["profile"]["full_name"] == "G'ofurov Ali Vali o'g'li"


def test_ai_red_needs_confidence_to_be_illegal() -> None:
    import uuid

    from app.ai.service import AIIssue
    from app.modules.scan.models import FindingKind, ScanJob
    from app.modules.scan.service import _ai_finding

    job = ScanJob(id=uuid.uuid4())
    sure = AIIssue(3, "yellow", "red", "Sud huquqi", "Sudga murojaat taqiqlangan", "FK 9", "Olib tashlang", 0.9)
    unsure = AIIssue(3, "yellow", "red", "Sud huquqi", "Sudga murojaat taqiqlangan", "FK 9", "Olib tashlang", 0.3)
    assert _ai_finding(job, sure, "t").kind == FindingKind.ILLEGAL and _ai_finding(job, sure, "t").severity == "red"
    low = _ai_finding(job, unsure, "t")
    assert low.kind == FindingKind.RISKY and "yurist tekshirsin" in low.explanation


async def test_scan_court_waiver_and_cash_currency_are_red(client: AsyncClient) -> None:
    h = await login(client, "+998981100004")
    text = (
        "PULLIK TIBBIY XIZMAT KO'RSATISH SHARTNOMASI\n"
        "4.1. To'lov 500 (besh yuz) AQSh dollari (naqd valyutada)ni tashkil etadi.\n"
        "7.2. Nizolar sudga murojaat qilish huquqidan mutlaqo mahrum etilgan holda faqat rahbar tomonidan hal etiladi.\n"
    )
    scan = (await client.post(f"{API}/scans/text", headers=h, json={"text": text})).json()
    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=h)).json()
    codes = {f["rule_code"] for f in rep["red_clauses"]}
    assert {"CLAUSE_WAIVER_OF_COURT", "CLAUSE_FOREIGN_CURRENCY_CASH"} <= codes
    assert all(f["suggestion"] for f in rep["red_clauses"])  # each red clause comes with advice


RES_RENT = """UY-JOYNI IJARAGA BERISH SHARTNOMASI
1. Ijaraga beruvchi Toshkent sh., Chilonzor 5-uydagi kvartirani Ijarachiga yashash uchun ijaraga beradi.
2. Ijara muddati 7 (yetti) yil.
3. Ijara haqi oyiga 4 000 000 so'm, har oyning 5-sanasigacha to'lanadi.
4. Ijaraga beruvchi istalgan vaqtda 10 kun oldin ogohlantirib shartnomani bir tomonlama bekor qilishi mumkin.
5. Nizolar sudda hal qilinadi.
"""


async def test_scan_residential_lease_red_clauses(client: AsyncClient) -> None:
    h = await login(client, "+998981100003")
    scan = (await client.post(f"{API}/scans/text", headers=h, json={"text": RES_RENT})).json()
    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=h)).json()
    assert rep["overall"]["contract_type"] == "rent_residential"
    red = {f["rule_code"]: f for f in rep["red_clauses"]}
    assert {"CLAUSE_RES_TERM_OVER_5Y", "CLAUSE_RES_LANDLORD_TERMINATION"} <= set(red)
    assert red["CLAUSE_RES_TERM_OVER_5Y"]["law_ref"].startswith("FK 612")


def test_document_title_from_heading() -> None:
    from app.modules.scan.analysis import document_title

    assert document_title("PULLIK TIBBIY XIZMAT KO'RSATISH SHARTNOMASI\n1.1. ...") == (
        "Pullik tibbiy xizmat ko'rsatish shartnomasi"
    )
    assert document_title("UY-JOYNI IJARAGA BERISH SHARTNOMASI № 17/2026\nToshkent") == (
        "Uy-joyni ijaraga berish shartnomasi"
    )
    assert document_title("1. Ijaraga beruvchi shartnoma bo'yicha majbur.") is None


async def test_report_says_which_contract(client: AsyncClient) -> None:
    h = await login(client, "+998981100005")
    scan = (await client.post(f"{API}/scans/text", headers=h, json={"text": RES_RENT})).json()
    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=h)).json()
    doc = rep["document"]
    assert doc["title"] == "Uy-joyni ijaraga berish shartnomasi" and doc["type_code"] == "rent_residential"
    assert doc["type_title"] and doc["clauses"] >= 5
    hist = (await client.get(f"{API}/scans", headers=h)).json()
    assert hist[0]["title"] == "Uy-joyni ijaraga berish shartnomasi"
