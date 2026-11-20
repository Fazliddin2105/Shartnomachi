"""lex.uz official model forms -> platform templates (parser, converter, CMS flow, monitoring)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.translit import cyr_to_lat
from app.db.session import session_scope
from app.integrations import lexuz
from app.modules.contracts import generator
from app.modules.moderation.models import ContentTask
from app.modules.templates import converter, service
from tests.conftest import API, EDITOR1, EDITOR2, login, login_privileged

FIX = Path(__file__).parent / "fixtures"
LABOR_HTML = (FIX / "lexuz_7220862_annex2.html").read_text(encoding="utf-8")
LOST_HTML = (FIX / "lexuz_lost_force.html").read_text(encoding="utf-8")


def _doc() -> lexuz.LexDocument:
    return lexuz.parse(LABOR_HTML, doc_id="7220862", lang="uz", url="https://lex.uz/uz/docs/7220862")


# --- pure ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cyr", "lat"),
    [
        ("Ўзбекистон", "O'zbekiston"),
        ("ёзма ерга", "yozma yerga"),
        ("компенсация цех", "kompensatsiya sex"),
        ("НАМУНАВИЙ ШАКЛИ", "NAMUNAVIY SHAKLI"),
        ("Шартнома", "Shartnoma"),
        ("ЖШШИР", "JSHSHIR"),
        ("Latin 123", "Latin 123"),
    ],
)
def test_transliteration(cyr: str, lat: str) -> None:
    assert cyr_to_lat(cyr) == lat


def test_parser_reads_metadata_and_annexes() -> None:
    d = _doc()
    assert d.title.startswith("758-сон 14.11.2024")
    assert str(d.in_force_from) == "2024-11-15" and d.edition_date is not None and not d.lost_force
    assert [a.number for a in d.annexes] == [1, 2]
    form = d.annex(number=2)
    assert "намунавий шакли" in form.title and "___" in form.text
    assert all("Hujjatga taklif" not in b.text for b in form.blocks)  # toolbar chrome removed
    lost = lexuz.parse(LOST_HTML, doc_id="-3532536", lang="uz", url="x")
    assert lost.lost_force and str(lost.lost_force_date) == "2019-10-14"


def test_converter_maps_official_blanks_to_rule_keys() -> None:
    prof = service.profiles()
    conv = converter.convert(_doc().annex(number=2), service.find_profile("7220862", 2), prof["generic"])
    keys = {f["key"] for s in conv.questionnaire["sections"] for f in s["fields"]}
    # the keys the existing labor rules use are produced from the official form
    assert {"probation_months", "weekly_hours", "annual_leave_days", "contract_kind", "end_date"} <= keys
    assert {"party_a.name", "party_b.name", "party_b.pinfl", "contract_date", "city"} <= keys
    assert conv.report["generic_fields"] == [] and conv.report["signature_blanks"] == 2
    # the employee's name occurs in 3 places of the form but is asked once
    assert sum(1 for s in conv.questionnaire["sections"] for f in s["fields"] if f["key"] == "party_b.name") == 1

    answers = {
        "party_b": {"name": "Aliyeva Malika"},
        "probation_months": 0,
        "weekly_hours": 40,
        "contract_kind": "fixed",
        "contract_date": "2026-11-20",
        "employment_kind": "part",
    }
    content = generator.render_content(
        template=conv.template,
        answers=answers,
        extra_clauses=[],
        type_code="labor",
        language="uz",
        form_requirement="simple",
    )
    text = "\n".join(s["text"] for s in content["sections"])
    assert "Xodim Aliyeva Malika" in text and "Sinov muddati sinovsiz" in text
    assert "haftasiga 40 soatgacha" in text and "o'rindoshlik" in text
    assert "muayyan muddatga" in text and "20.11.2026" in content["header"]
    assert "__________" in text  # unanswered blanks stay fillable by hand
    assert "(sana, imzo va muhr)" in text


# --- CMS flow over a mocked lex.uz -------------------------------------------------------------------


@pytest.fixture
def lexuz_site() -> Iterator[dict[str, str]]:
    pages = {"/uz/docs/7220862": LABOR_HTML, "/uz/docs/-3532536": LOST_HTML}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "LexLabImporter" in request.headers["user-agent"]
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    lexuz.configure_transport(httpx.MockTransport(handler))
    yield pages
    lexuz.configure_transport(None)


async def test_import_approve_and_use_official_template(client: AsyncClient, lexuz_site: dict[str, str]) -> None:
    e1 = await login_privileged(client, EDITOR1)
    e2 = await login_privileged(client, EDITOR2)

    prev = (await client.get(f"{API}/cms/templates/lexuz/7220862", headers=e1)).json()
    assert prev["lost_force"] is False and prev["annexes"][1]["profile"] == "labor_vm758_annex2"

    r = await client.post(
        f"{API}/cms/templates/import-lexuz", headers=e1, json={"doc_id": "7220862", "annex": 2, "target_code": "labor"}
    )
    assert r.status_code == 201, r.text
    tv = r.json()
    assert tv["status"] == "draft" and tv["source"]["kind"] == "lexuz" and tv["source"]["annex"] == 2
    assert tv["report"]["fields"] >= 30
    assert "меҳнат шартномаси" in tv["original_text"]  # verbatim official text is kept as provenance

    # four-eyes: the importing editor can't approve
    r = await client.post(f"{API}/cms/templates/{tv['id']}/approve", headers=e1)
    assert r.json()["error"]["code"] == "four_eyes"
    r = await client.post(f"{API}/cms/templates/{tv['id']}/approve", headers=e2)
    assert r.json()["contract_type"] == "labor"

    t = (await client.get(f"{API}/contract-types/labor")).json()
    assert t["source"]["kind"] == "lexuz" and t["source"]["doc_id"] == "7220862"
    assert t["questionnaire"]["imported"] is True

    # a citizen drafts a labor contract on the official form; the rule engine still guards it
    user = await login(client, "+998971000001")
    c = (await client.post(f"{API}/contracts", headers=user, json={"type_code": "labor", "my_role": "A"})).json()
    r = await client.patch(
        f"{API}/contracts/{c['id']}/answers",
        headers=user,
        json={
            "answers": {
                "party_a": {"name": "Test MChJ"},
                "party_b": {"name": "Karimov Sardor"},
                "probation_months": 6,
                "weekly_hours": 48,
                "annual_leave_days": 21,
                "contract_kind": "indefinite",
            }
        },
    )
    reds = {f["rule_code"] for f in r.json()["findings"] if f["severity"] == "red"}
    assert {"LABOR_PROBATION_MAX", "LABOR_WEEKLY_HOURS_MAX"} <= reds
    doc = (await client.get(f"{API}/contracts/{c['id']}/preview", headers=user)).json()
    assert "mehnat shartnomasi" in doc["title"]
    assert any("Karimov Sardor" in s["text"] for s in doc["sections"])
    listed = (await client.get(f"{API}/contracts", headers=user)).json()
    assert listed[0]["party_names"] == {"A": "Test MChJ", "B": "Karimov Sardor"}


async def test_lost_force_document_is_refused(client: AsyncClient, lexuz_site: dict[str, str]) -> None:
    e1 = await login_privileged(client, EDITOR1)
    r = await client.post(f"{API}/cms/templates/import-lexuz", headers=e1, json={"doc_id": "-3532536"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "lexuz_lost_force"
    r = await client.post(f"{API}/cms/templates/import-lexuz", headers=e1, json={"doc_id": "abc"})
    assert r.json()["error"]["code"] == "lexuz_bad_id"


async def test_monitoring_flags_changed_source(client: AsyncClient, lexuz_site: dict[str, str]) -> None:
    async with session_scope() as db:
        tv = await service.import_from_lexuz(
            db, doc_id="7220862", annex_number=2, target_code="labor_monitor_test", title=None, latin=True, author=None
        )
        await service.approve(db, tv, None, system=True)
        assert (await service.check_sources(db))["changed"] == []

    # lex.uz publishes a new edition of the form
    lexuz_site["/uz/docs/7220862"] = LABOR_HTML.replace("ички меҳнат тартибига", "ички меҳнат тартиби қоидаларига", 1)
    async with session_scope() as db:
        res = await service.check_sources(db)
        assert "labor_monitor_test" in res["changed"]
        task = await db.scalar(select(ContentTask).where(ContentTask.reason.contains("namunaviy shakl o'zgargan")))
        assert task is not None
    t = (await client.get(f"{API}/contract-types/labor_monitor_test")).json()
    assert t["source"]["needs_review"] is True
    json.dumps(t)  # serialisable
