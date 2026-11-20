"""Organization templates imported from the user's DOCX forms (rent_commercial, rent_private, loan_notarial)."""

from __future__ import annotations

import io
from datetime import timedelta

from docx import Document
from httpx import AsyncClient

from app.core.timeutils import today_local
from app.modules.contracts.generator import _words
from app.modules.scan import analysis
from app.workers import queue
from tests.conftest import API, login
from tests.test_ai import FakeLLM, fake_llm  # noqa: F401  (fixture)

TODAY = today_local()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


COMMERCIAL = {
    "contract_number": "17/2026",
    "city": "Toshkent sh.",
    "contract_date": TODAY.isoformat(),
    "party_a": {
        "name": "“Toshkent Invest” MChJ",
        "director_position": "direktor",
        "director": "Karimov Abdullo Valiyevich",
        "address": "Toshkent sh., Yunusobod t., 4-mavze, 12",
        "account": "20208000900123456001",
        "stir": "305891247",
        "mfo": "00873",
        "oked": "68200",
    },
    "party_b": {
        "name": "“Smart Cloud” MChJ",
        "director_position": "bosh direktor",
        "director": "Aliyev Sardor Rustamovich",
        "address": "Toshkent sh., Chilonzor t., 9-kvartal, 3",
        "account": "20208000500987654001",
        "stir": "307123456",
        "mfo": "00440",
        "oked": "62010",
    },
    "property_address": "Toshkent sh., Mirobod t., Afrosiyob ko‘chasi, 7",
    "property_area": 250,
    "floors": 2,
    "land_area": 120,
    "purpose": "ofis",
    "start_date": _iso(1),
    "end_date": _iso(300),
    "rent_amount": 4_500_000,
    "payment_day": 5,
    "payment_method": "bank_transfer",
    "utilities_included": "excluded",
    "repairs_by": "landlord",
    "handover_days": 3,
    "sale_notice_days": 30,
    "copies": 2,
}


async def _create(client: AsyncClient, h: dict, code: str, answers: dict) -> tuple[str, dict]:
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": code, "my_role": "A"})).json()
    r = await client.patch(f"{API}/contracts/{c['id']}/answers", headers=h, json={"answers": answers})
    assert r.status_code == 200, r.text
    return c["id"], r.json()


def _docx_text(data: bytes) -> str:
    d = Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def test_amount_in_words() -> None:
    assert _words(4_500_000) == "to‘rt million besh yuz ming"
    assert _words(123_456_789) == "bir yuz yigirma uch million to‘rt yuz ellik olti ming yetti yuz sakson to‘qqiz"
    assert _words(0) == "nol" and _words("abc") == ""


async def test_types_are_listed_with_provenance(client: AsyncClient) -> None:
    types = {t["code"]: t for t in (await client.get(f"{API}/contract-types")).json()}
    for code, file in (
        ("rent_commercial", "Noturar_joy_ijara_shartnomasi.docx"),
        ("rent_private", "Ijara_shartnomasi_shabloni.docx"),
        ("loan_notarial", "Qarz_shartnomasi.docx"),
    ):
        assert types[code]["source"]["kind"] == "organization" and types[code]["source"]["file"] == file


async def test_rent_commercial_full_text_and_docx(client: AsyncClient) -> None:
    h = await login(client, "+998934000001")
    cid, report = await _create(client, h, "rent_commercial", COMMERCIAL)
    assert report["ready"] is True and report["summary"]["counts"]["red"] == 0, report

    pv = (await client.get(f"{API}/contracts/{cid}/preview", headers=h)).json()
    text = "\n".join(s["text"] for s in pv["sections"])
    assert pv["title"].startswith("SHARTNOMA № 17/2026")
    assert "“Toshkent Invest” MChJ nomidan direktor Karimov Abdullo Valiyevich" in pv["preamble"]
    assert "umumiy maydoni 250 kv.mdan iborat bo‘lgan 2 qavatli noturar binoni hamda" in text
    assert "120 kv.m hududni" in text
    assert "4 500 000 (to‘rt million besh yuz ming) so‘m" in text
    assert "har oyning 5-sanasigacha pul ko‘chirish yo‘li bilan" in text
    assert "boshqa to‘lovlar kirmaydi" in text and "“IJARAGA BERUVCHI” hisobidan" in text
    assert "3.1.4." not in text  # optional "(mavjud bo‘lsa)" items are omitted when empty
    assert "6.2. Mazkur shartnoma 2 nusxadan" in text

    r = await client.post(f"{API}/contracts/{cid}/generate", headers=h, json={"language": "uz"})
    assert r.status_code == 200, r.text
    dl = await client.get(f"{API}/contracts/{cid}/versions/1/download?format=docx", headers=h)
    doc = _docx_text(dl.content)
    for needle in (
        "7. Tomonlarning manzillari va bank rekvizitlari",
        "IJARAGA BERUVCHI",
        "IJARAGA OLUVCHI",
        "STIR: 305891247",
        "MFO: 00873",
        "OKED: 68200",
        "Rahbar: Karimov Abdullo Valiyevich",
        "M.O‘.",
        "binolardan foydalanish departamentida hisobga olindi",
    ):
        assert needle in doc, needle


async def test_rent_commercial_rules_and_formats(client: AsyncClient) -> None:
    h = await login(client, "+998934000002")
    bad = {
        **COMMERCIAL,
        "end_date": _iso(-5),
        "payment_method": "cash",
        "party_a": {**COMMERCIAL["party_a"], "stir": "12345", "mfo": "1"},
    }
    cid, report = await _create(client, h, "rent_commercial", bad)
    codes = {f["rule_code"]: f["severity"] for f in report["findings"]}
    assert codes["RENTC_END_BEFORE_START"] == "red" and codes["RENTC_CASH_BETWEEN_COMPANIES"] == "yellow"
    assert {e["field"] for e in report["field_errors"]} == {"party_a.stir", "party_a.mfo"}
    r = await client.post(f"{API}/contracts/{cid}/generate", headers=h, json={"acknowledge_red": True})
    assert r.json()["error"]["code"] == "answers_incomplete"

    # Without land the clause is grammatical and mentions no land
    no_land = {**COMMERCIAL, "land_area": None}
    cid2, _ = await _create(client, h, "rent_commercial", no_land)
    text = "\n".join(
        s["text"] for s in (await client.get(f"{API}/contracts/{cid2}/preview", headers=h)).json()["sections"]
    )
    assert "qavatli noturar binoni " in text and "hududni" not in text and "mazkur binodan ofis maqsadida" in text

    # A lease of a year or more needs registration (form rule)
    long = {**COMMERCIAL, "end_date": _iso(400)}
    _, rep = await _create(client, h, "rent_commercial", long)
    assert rep["form"]["requirement"] == "registration"


async def test_rent_private_utilities_choice_is_consistent(client: AsyncClient) -> None:
    h = await login(client, "+998934000003")
    base = {
        "city": "Samarqand sh.",
        "contract_date": TODAY.isoformat(),
        "party_a": {"name": "Rahimov Bobur", "address": "Samarqand", "tin": "31205941230042", "phone": "+998901234567"},
        "party_b": {
            "name": "Tursunova Malika",
            "address": "Samarqand",
            "tin": "31205941230043",
            "phone": "998907654321",
        },
        "property_address": "Samarqand sh., Registon ko‘chasi, 15",
        "property_area": 64,
        "rooms": 3,
        "purpose": "yashash",
        "start_date": _iso(1),
        "end_date": _iso(200),
        "rent_amount": 3_000_000,
        "payment_day": 10,
        "payment_method": "bank_transfer",
        "handover_days": 2,
        "sale_notice_days": 30,
        "copies": 2,
    }
    cid, rep = await _create(client, h, "rent_private", {**base, "utilities": "tenant"})
    assert "RENTP_TRANSFER_NO_ACCOUNT" in {f["rule_code"] for f in rep["findings"]}
    text = "\n".join(
        s["text"] for s in (await client.get(f"{API}/contracts/{cid}/preview", headers=h)).json()["sections"]
    )
    assert "boshqa to‘lovlar kirmaydi" in text and "2.4. Kommunal xizmatlar uchun to‘lovlar Ijaraga oluvchi" in text
    assert "3 xonali binoni" in text and "3 000 000 (uch million) so‘m" in text

    cid2, rep2 = await _create(client, h, "rent_private", {**base, "utilities": "included", "payment_method": "cash"})
    assert "RENTP_TRANSFER_NO_ACCOUNT" not in {f["rule_code"] for f in rep2["findings"]}
    text2 = "\n".join(
        s["text"] for s in (await client.get(f"{API}/contracts/{cid2}/preview", headers=h)).json()["sections"]
    )
    assert "boshqa to‘lovlar kiradi" in text2 and "Kommunal xizmatlar uchun to‘lovlar" not in text2
    assert "naqd pul to‘lash yo‘li bilan" in text2


async def test_loan_notarial_text_blanks_and_rules(client: AsyncClient) -> None:
    h = await login(client, "+998934000004")
    answers = {
        "notarial_district": "Toshkent shahar Yunusobod tumani",
        "contract_date": TODAY.isoformat(),
        "party_a": {
            "name": "Karimov Abdullo",
            "birth_date": "1985-03-12",
            "address": "Toshkent sh., Yunusobod t., 4-mavze, 12-uy",
            "passport": "AA 1234567",
            "passport_issued_by": "Yunusobod tumani IIB",
            "passport_issued_date": "2015-06-01",
        },
        "party_b": {
            "name": "Aliyev Sardor",
            "birth_date": "1990-07-25",
            "address": "Toshkent sh., Chilonzor t., 9-kvartal, 3-uy",
            "passport": "AB7654321",
            "passport_issued_by": "Chilonzor tumani IIB",
            "passport_issued_date": "2018-02-14",
        },
        "amount": 20_000_000,
        "loan_term": "6 (olti) oy",
        "return_date": _iso(182),
        "loan_place": "Toshkent sh., Yunusobod tumani",
    }
    cid, rep = await _create(client, h, "loan_notarial", answers)
    assert rep["ready"] is True and "LOANN_NOTARY_FORM" in {f["rule_code"] for f in rep["findings"]}
    pv = (await client.get(f"{API}/contracts/{cid}/preview", headers=h)).json()
    assert "12.03.1985da tug‘ilgan Karimov Abdullo (pasport AA 1234567" in pv["preamble"]
    text = "\n".join(s["text"] for s in pv["sections"])
    assert "1. Men — QARZ BERUVCHI 20 000 000 so‘m" in text and "6 (olti) oy muddatga" in text
    assert "____________________ xususiy amaliyot" in text  # notary blank left for the notary
    assert all(s["title"] == "" for s in pv["sections"])

    r = await client.post(f"{API}/contracts/{cid}/generate", headers=h, json={"language": "uz"})
    assert r.status_code == 200, r.text
    doc = _docx_text((await client.get(f"{API}/contracts/{cid}/versions/1/download?format=docx", headers=h)).content)
    assert "Notariusning tasdiqlov yozuvi:" in doc and "QARZ BERUVCHI" in doc and "(F.I.Sh. va imzo)" in doc

    bad = {**answers, "return_date": _iso(-1), "party_a": {**answers["party_a"], "passport": "1234"}}
    _, rep = await _create(client, h, "loan_notarial", bad)
    assert {f["rule_code"]: f["severity"] for f in rep["findings"]}["LOANN_RETURN_NOT_AFTER_CONTRACT"] == "red"
    assert [e["field"] for e in rep["field_errors"]] == ["party_a.passport"]


# --- the organization template as the reference for the scanner and the AI ---------------------------


async def _uploaded_from_template(client: AsyncClient, h: dict, drop: tuple[str, ...]) -> str:
    """A third-party contract built from the organization form, with some clauses removed."""
    cid, _ = await _create(client, h, "rent_commercial", COMMERCIAL)
    pv = (await client.get(f"{API}/contracts/{cid}/preview", headers=h)).json()
    lines = [pv["title"], pv["preamble"]]
    for s in pv["sections"]:
        lines.append(s["title"])
        lines += [ln for ln in s["text"].splitlines() if not ln.startswith(drop)]
    return "\n".join(lines)


async def test_scanner_compares_uploaded_contract_with_organization_template(client: AsyncClient) -> None:
    h = await login(client, "+998934000005")
    text = await _uploaded_from_template(client, h, drop=("3.4.6.", "3.2.3."))
    scan = (await client.post(f"{API}/scans/text", headers=h, json={"text": text})).json()
    assert scan["contract_type_code"] == "rent_commercial" and scan["type_detected"] is True
    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=h)).json()
    tc = rep["overall"]["template_check"]
    assert tc["source"]["kind"] == "organization" and tc["source"]["file"] == "Noturar_joy_ijara_shartnomasi.docx"
    missing = {m["key"] for m in tc["missing"]}
    assert missing == {"rights:3.4.6", "rights:3.2.3"}, tc["missing"]
    assert tc["conformity"] >= 0.85
    cards = [f for f in rep["missing_elements"] if f["source"] == "template"]
    assert {c["explanation"].split(": ", 1)[0] for c in cards} == {"Tashkilot shablonidagi band topilmadi"}
    assert any("yozma roziligisiz" in c["explanation"] for c in cards)


async def test_ai_review_gets_organization_template_as_reference(client: AsyncClient, fake_llm: FakeLLM) -> None:  # noqa: F811
    h = await login(client, "+998934000006")
    text = await _uploaded_from_template(client, h, drop=("3.4.6.",))
    await client.post(f"{API}/scans/text", headers=h, json={"text": text})
    await queue.drain()
    prompt = fake_llm.requests[-1]["messages"][-1]["content"]
    assert "Tashkilot tasdiqlagan shablon bandlari — solishtiring:" in prompt
    assert "3.4.6. “IJARAGA BERUVCHI”ning yozma roziligisiz" in prompt  # the clause the upload lacks
    assert "{{" not in prompt and "{%" not in prompt  # rendered text, never template syntax
    assert "305891247" not in prompt  # PII still masked for the external model


def test_type_detection_prefers_distinctive_keywords() -> None:
    import json as _json

    from app.seed import content_dir

    types = []
    for p in sorted((content_dir() / "contract_types").glob("*.json")):
        d = _json.loads(p.read_text(encoding="utf-8"))
        types.append((d["code"], d["detect_keywords"]))
    samples = {
        "rent_commercial": "SHARTNOMA (Noturar joyni ijaraga berish to‘g‘risida). “IJARAGA BERUVCHI” “IJARAGA OLUVCHI”ga "
        "noturar binoni ijaraga beradi. IJARAGA OLUVCHI ijara haqini to‘laydi.",
        "rent_private": "ИЖАРА ШАРТНОМАСИ. Ижарага берувчи жисмоний шахс ва ижарага олувчи жисмоний шахс. "
        "IJARA SHARTNOMASI: jismoniy shaxs 3 xonali binoni ijaraga beradi.",
        "rent_residential": "IJARA SHARTNOMASI. Ijaraga beruvchi kvartirani Ijarachiga beradi. Ijarachi to'laydi.",
        "loan_notarial": "QARZ SHARTNOMASI. Xususiy amaliyot bilan shug‘ullanuvchi notarius. Qarz beruvchi va "
        "Qarz oluvchi. Notarius tomonidan tushuntirildi.",
        "loan": "QARZ SHARTNOMASI. Qarz beruvchi qarz oluvchiga qarz beradi, qarz oluvchi qarzni qaytaradi.",
    }
    for expected, text in samples.items():
        assert analysis.detect_type(text, types) == expected, expected
