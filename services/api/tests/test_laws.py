"""Law corpus from lex.uz and rules grounded in it (articles re-checked against the published text)."""

from __future__ import annotations

import json
from datetime import timedelta

from httpx import AsyncClient

from app.core.timeutils import today_local
from app.modules.laws import corpus
from app.modules.rules import engine
from app.seed import content_dir
from tests.conftest import API, login
from tests.test_ai import FakeLLM, fake_llm  # noqa: F401  (fixture)

TODAY = today_local()


def _rules() -> dict[str, dict]:
    return {
        r["code"]: r for r in json.loads((content_dir() / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]
    }


def test_corpus_has_the_codes_and_key_articles() -> None:
    assert {"fk1", "fk2", "mk", "consumer"} <= set(corpus.available())
    a = corpus.article("fk1", 326)
    assert a["title"] == "Neustoykani kamaytirish" and a["url"].startswith("https://lex.uz/uz/docs/-111189#")
    assert "sud neustoykani kamaytirishga haqli" in a["text"]
    assert "uch oydan" in corpus.article("mk", 130)["text"]  # probation
    assert "qirq soat" in corpus.article("mk", 182)["text"]  # 40 hours
    assert "yigirma bir kalendar kun" in corpus.article("mk", 217)["text"]  # 21 days leave
    assert "besh yildan ortiq" in corpus.article("fk2", 612)["text"]  # residential lease <= 5 years
    assert "uch oy avval" in corpus.article("fk2", 615)["text"]
    assert corpus.cite("fk2", 498) == "FK 498-modda. Ayirboshlash shartnomasi boʻyicha baho va xarajatlar"
    assert corpus.search("qarz shartnomasining shakli", codes=["fk2"])[0]["number"] == "733"


def test_every_legal_rule_points_to_a_real_article() -> None:
    advisory = {
        "LARGE_AMOUNT_ADVICE",
        "CLAUSE_AUTO_PROLONGATION",
        "RENTC_CASH_BETWEEN_COMPANIES",
        "RENTP_TRANSFER_NO_ACCOUNT",
        "VEX_NOTARY_AND_REGISTRATION",
    }
    for code, r in _rules().items():
        if code in advisory:
            continue
        assert r.get("law_articles"), code
        for ref in r["law_articles"]:
            art = corpus.article(ref["code"], ref["number"])  # raises if the article does not exist
            assert art["title"] in r["law_ref"], code
        assert r["lex_url"].startswith("https://lex.uz/uz/docs/"), code
    for p in (content_dir() / "contract_types").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        for ref in d["legal_refs"]:
            assert corpus.article(ref["code"], ref["number"])["url"] == ref["lex_url"], (p.stem, ref)


def test_probation_rule_follows_mk_130() -> None:
    r = _rules()
    rule = r["LABOR_PROBATION_MAX"]["rule_json"]
    manager = r["LABOR_PROBATION_MAX_MANAGER"]["rule_json"]
    ctx = lambda months, pos: {"answers": {"probation_months": months, "position": pos}}  # noqa: E731
    assert engine.evaluate(rule, ctx(6, "Sotuv menejeri")) is True  # ordinary employee: max 3 months
    assert engine.evaluate(rule, ctx(6, "Bosh buxgalter")) is False  # allowed up to 6 for chief accountant
    assert engine.evaluate(manager, ctx(7, "Direktor")) is True  # never more than 6


def test_poa_age_operator() -> None:
    r = _rules()["VEX_POA_OLDER_3Y"]["rule_json"]
    base = {"answers": {"b_via_representative": "yes", "contract_date": "2026-11-20"}}
    assert engine.evaluate(r, {"answers": {**base["answers"], "party_b": {"poa_date": "2022-01-01"}}}) is True
    assert engine.evaluate(r, {"answers": {**base["answers"], "party_b": {"poa_date": "2025-01-01"}}}) is False


async def test_laws_api(client: AsyncClient) -> None:
    src = (await client.get(f"{API}/laws")).json()
    assert {s["code"] for s in src} >= {"fk1", "fk2", "mk", "consumer"} and all(s["edition_date"] for s in src)
    a = (await client.get(f"{API}/laws/fk2/articles/733")).json()
    assert a["title"] == "Qarz shartnomasining shakli" and "bazaviy hisoblash miqdorining oʻn baravaridan" in a["text"]
    hits = (await client.get(f"{API}/laws/search", params={"q": "dastlabki sinov muddati", "code": "mk"})).json()
    assert hits[0]["number"] == "130"
    assert (await client.get(f"{API}/laws/fk2/articles/99999")).status_code == 404


async def test_findings_carry_article_and_lex_url(client: AsyncClient) -> None:
    h = await login(client, "+998938000001")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "labor", "my_role": "A"})).json()
    r = (
        await client.patch(
            f"{API}/contracts/{c['id']}/answers",
            headers=h,
            json={"answers": {"probation_months": 5, "position": "Hisobchi", "weekly_hours": 48}},
        )
    ).json()
    by = {f["rule_code"]: f for f in r["findings"]}
    assert by["LABOR_PROBATION_MAX"]["law_ref"].startswith("MK 130-modda")
    assert by["LABOR_WEEKLY_HOURS_MAX"]["lex_url"].startswith("https://lex.uz/uz/docs/-6257288#")


async def test_residential_template_follows_fk_612_615(client: AsyncClient) -> None:
    h = await login(client, "+998938000002")
    c = (
        await client.post(f"{API}/contracts", headers=h, json={"type_code": "rent_residential", "my_role": "A"})
    ).json()
    answers = {
        "party_a": {"name": "Aliyev Vali", "pinfl": "31234567890123"},
        "party_b": {"name": "Karimov Sardor", "pinfl": "31234567890124"},
        "city": "Toshkent",
        "contract_date": TODAY.isoformat(),
        "property_address": "Toshkent sh., Chilonzor 5",
        "rent_amount": 3_000_000,
        "payment_day": 5,
        "start_date": (TODAY + timedelta(days=1)).isoformat(),
        "utilities_paid_by": "tenant",
    }
    r = (await client.patch(f"{API}/contracts/{c['id']}/answers", headers=h, json={"answers": answers})).json()
    assert r["form"]["requirement"] == "simple"  # uy-joy: no state registration (FK 603), only tax registration
    assert "RENT_RES_TAX_REGISTRATION" in {f["rule_code"] for f in r["findings"]}
    text = "\n".join(
        s["text"] for s in (await client.get(f"{API}/contracts/{c['id']}/preview", headers=h)).json()["sections"]
    )
    assert "besh yil muddatga" in text and "muddatsiz" not in text  # FK 612
    assert "kamida 90 kun oldin" in text and "FK 615-modda" in text  # tenant-only notice, landlord via court

    r = (
        await client.patch(
            f"{API}/contracts/{c['id']}/answers",
            headers=h,
            json={"answers": {"end_date": (TODAY + timedelta(days=6 * 365)).isoformat(), "notice_days": 120}},
        )
    ).json()
    codes = {f["rule_code"]: f["severity"] for f in r["findings"]}
    assert codes["RENT_RES_TERM_OVER_5Y"] == "red" and codes["RENT_TENANT_NOTICE_OVER_LAW"] == "yellow"


async def test_ai_review_is_grounded_in_article_texts(client: AsyncClient, fake_llm: FakeLLM) -> None:  # noqa: F811
    h = await login(client, "+998938000003")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})).json()
    await client.patch(
        f"{API}/contracts/{c['id']}/answers",
        headers=h,
        json={
            "answers": {
                "party_a": {"name": "Aliyev Vali"},
                "party_b": {"name": "Karimov Sardor"},
                "city": "Toshkent",
                "contract_date": TODAY.isoformat(),
                "amount": 5_000_000,
                "currency": "UZS",
                "given_date": TODAY.isoformat(),
                "return_date": (TODAY + timedelta(days=60)).isoformat(),
            }
        },
    )
    assert (await client.post(f"{API}/contracts/{c['id']}/ai/review", headers=h)).status_code == 200
    prompt = fake_llm.requests[-1]["messages"][-1]["content"]
    assert "O'zbekiston qonunchiligi (lex.uz, amaldagi tahrir)" in prompt
    assert "[FK 733-modda. Qarz shartnomasining shakli]" in prompt and "oʻn baravaridan" in prompt
    system = fake_llm.requests[-1]["messages"][0]["content"]
    assert "AYNAN shu matnga asoslang" in system


async def test_resolve_reference_text(client: AsyncClient) -> None:
    arts = (
        await client.get(f"{API}/laws/resolve", params={"ref": "FK 237-modda. …; FK 615-modda; MK 130-modda"})
    ).json()
    assert [(a["code"], a["number"]) for a in arts] == [("fk1", "237"), ("fk2", "615"), ("mk", "130")]


async def test_field_warnings_carry_article(client: AsyncClient) -> None:
    h = await login(client, "+998938000004")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "labor", "my_role": "A"})).json()
    r = (
        await client.patch(f"{API}/contracts/{c['id']}/answers", headers=h, json={"answers": {"weekly_hours": 48}})
    ).json()
    w = r["field_warnings"]["weekly_hours"][0]
    assert w["law_ref"].startswith("MK 182-modda") and w["lex_url"].startswith("https://lex.uz/")
