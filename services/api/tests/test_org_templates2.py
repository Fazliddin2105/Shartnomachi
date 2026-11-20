"""Organization templates: vehicle exchange (notarial) and paid medical services."""

from __future__ import annotations

import io
import json
from datetime import timedelta

from docx import Document
from httpx import AsyncClient

from app.core.timeutils import today_local
from app.modules.contracts.generator import _date_long
from app.modules.scan import analysis
from app.seed import content_dir
from tests.conftest import API, login

TODAY = today_local()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _person(name: str, pinfl: str) -> dict:
    return {
        "name": name,
        "address": "Toshkent sh., Yunusobod t., Amir Temur ko‘chasi",
        "house": "12",
        "birth_year": 1985,
        "passport_series": "AA",
        "passport_number": "1234567",
        "passport_issued_by": "Yunusobod tumani IIB",
        "passport_issued_date": "2015-06-01",
        "pinfl": pinfl,
    }


def _vehicle(make: str, plate: str) -> dict:
    return {
        "make": make,
        "year": 2019,
        "engine_no": "B15D2-123456",
        "body_no": "XWB3L32EDKA000001",
        "color": "oq",
        "plate": plate,
        "hp": 106,
        "reg_issuer": "Toshkent shahar IIB YHXX",
        "reg_date": "2019-05-10",
        "reg_series": "AAF",
        "reg_number": "1234567",
    }


VEHICLE = {
    "notarial_district": "Toshkent shahar Yunusobod tumani notarial okrugi",
    "contract_date": TODAY.isoformat(),
    "party_a": {
        **_person("Karimov Abdullo", "31205941230042"),
        "phone": "+998901234567",
        "vehicle": _vehicle("Chevrolet Cobalt", "01 A 123 BC"),
    },
    "b_via_representative": "no",
    "party_b": {**_person("Aliyev Sardor", "31205941230043"), "vehicle": _vehicle("Chevrolet Nexia 3", "10 B 777 AA")},
    "value_a": 120_000_000,
    "value_b": 120_000_000,
    "expenses_paid_by": "both",
}

MEDICAL = {
    "contract_number": "T-15",
    "city": "Toshkent sh.",
    "contract_date": TODAY.isoformat(),
    "party_a": {
        "name": "“Shifo Med” MChJ",
        "director_position": "direktor",
        "director": "Rahimova Dilnoza",
        "address": "Toshkent sh., Mirobod t., 5",
        "account": "20208000900123456001",
        "bank": "«Kapitalbank» ATB",
        "mfo": "00974",
        "stir": "306123456",
        "oked": "86100",
        "phone": "+998712001020",
    },
    "party_b": {
        "name": "Tursunov Bekzod",
        "address": "Toshkent sh., Chilonzor t., 9-kvartal, 3",
        "passport": "AB 7654321",
        "passport_issued_date": "2018-02-14",
        "passport_issued_by": "Chilonzor tumani IIB",
        "tin": "31205941230044",
        "phone": "+998907654321",
    },
    "service_address": "Toshkent sh., Mirobod t., 5",
    "start_date": _iso(1),
    "end_date": _iso(10),
    "price": 2_500_000,
    "payment_days": 3,
    "payment_method": "card",
    "materials_included": "excluded",
}


async def _contract(client: AsyncClient, h: dict, code: str, answers: dict) -> tuple[str, dict]:
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


def test_long_notarial_date() -> None:
    assert _date_long("2026-11-20") == "«20» noyabr ikki ming yigirma oltinchi yil"
    assert _date_long("2025-01-05") == "«05» yanvar ikki ming yigirma beshinchi yil"
    assert _date_long("2030-12-31") == "«31» dekabr ikki ming o‘ttizinchi yil"


async def test_vehicle_exchange_text_cross_transfer_and_docx(client: AsyncClient) -> None:
    h = await login(client, "+998937000001")
    cid, rep = await _contract(client, h, "vehicle_exchange", VEHICLE)
    assert rep["ready"] is True and rep["summary"]["counts"]["red"] == 0, rep
    assert "VEX_NOTARY_AND_REGISTRATION" in {f["rule_code"] for f in rep["findings"]}

    pv = (await client.get(f"{API}/contracts/{cid}/preview", headers=h)).json()
    assert _date_long(TODAY) in pv["subheader"] and "notarial okrugi" in pv["subheader"]
    assert "1985-yilda tug‘ilgan Karimov Abdullo (pasport/ID-karta seriyasi AA raqami 1234567" in pv["preamble"]
    assert "ishonchnoma" not in pv["preamble"]  # B acts personally
    text = "\n".join(s["text"] for s in pv["sections"])
    assert "— Birinchi tarafga tegishli bo‘lgan: rusumi (markasi) Chevrolet Cobalt" in text
    assert "shassi raqami —" in text  # optional chassis left empty
    assert "120 000 000 (bir yuz yigirma million) so‘mga" in text
    # clause 5: each side receives the *other* side's car
    assert "Birinchi taraf (Karimov Abdullo) egaligiga rusumi Chevrolet Nexia 3" in text
    assert "Ikkinchi taraf (Aliyev Sardor) egaligiga rusumi Chevrolet Cobalt" in text
    assert "xarajatlarni taraflar teng miqdorda to‘ladi" in text

    assert (await client.post(f"{API}/contracts/{cid}/generate", headers=h, json={})).status_code == 200
    doc = _docx_text((await client.get(f"{API}/contracts/{cid}/versions/1/download?format=docx", headers=h)).content)
    for needle in (
        "IMZOLAR:",
        "(Birinchi taraf F.I.Sh. va imzosi)",
        "(Ikkinchi taraf / vakil F.I.Sh. va imzosi)",
        "Notariusning tasdiqlov yozuvi",
        "Reyestr raqami",
        "AVTOTRANSPORT VOSITASINI AYIRBOSHLASH",
    ):
        assert needle in doc, needle


async def test_vehicle_exchange_representative_and_rules(client: AsyncClient) -> None:
    h = await login(client, "+998937000002")
    via_rep = {
        **VEHICLE,
        "b_via_representative": "yes",
        "party_b": {
            "name": "Aliyev Sardor",
            "address": "Samarqand sh.",
            "house": "4",
            "vehicle": _vehicle("Chevrolet Nexia 3", "10 B 777 AA"),
        },
    }
    cid, rep = await _contract(client, h, "vehicle_exchange", via_rep)
    assert {"party_b.rep.name", "party_b.poa_date", "party_b.poa_reg_no"} <= set(rep["missing_fields"])
    assert "party_b.passport_series" not in rep["missing_fields"]  # B's own passport not needed via a representative

    rep = (
        await client.patch(
            f"{API}/contracts/{cid}/answers",
            headers=h,
            json={
                "answers": {
                    "party_b.rep": _person("Valiyev Jasur", "31205941230045"),
                    "party_b.poa_notary": "Samarqand shahar 3-son",
                    "party_b.poa_date": _iso(5),  # after the contract date -> no authority on that day
                    "party_b.poa_reg_no": "2-1234",
                }
            },
        )
    ).json()
    assert rep["ready"] is True
    assert {f["rule_code"]: f["severity"] for f in rep["findings"]}["VEX_POA_AFTER_CONTRACT"] == "red"
    rep = (
        await client.patch(
            f"{API}/contracts/{cid}/answers", headers=h, json={"answers": {"party_b.poa_date": _iso(-30)}}
        )
    ).json()
    assert "VEX_POA_AFTER_CONTRACT" not in {f["rule_code"] for f in rep["findings"]}
    pv = (await client.get(f"{API}/contracts/{cid}/preview", headers=h)).json()
    assert "Aliyev Sardor nomidan Samarqand shahar 3-son xususiy amaliyot" in pv["preamble"]
    assert "Valiyev Jasur (pasport/ID-karta seriyasi AA" in pv["preamble"]
    assert "1. Men — Karimov Abdullo hamda men — Valiyev Jasur" in pv["sections"][0]["text"]

    rep = (
        await client.patch(
            f"{API}/contracts/{cid}/answers",
            headers=h,
            json={"answers": {"value_b": 100_000_000, "party_b.vehicle.plate": "01 A 123 BC"}},
        )
    ).json()
    codes = {f["rule_code"]: f["severity"] for f in rep["findings"]}
    assert codes["VEX_UNEQUAL_VALUE"] == "yellow" and codes["VEX_SAME_PLATE"] == "red"
    g = await client.post(f"{API}/contracts/{cid}/generate", headers=h, json={})
    assert g.json()["error"]["code"] == "illegal_clauses"


async def test_medical_paid_text_requisites_and_obligations(client: AsyncClient) -> None:
    a = await login(client, "+998937000003")
    cid, rep = await _contract(client, a, "medical_paid", MEDICAL)
    assert rep["ready"] is True and rep["summary"]["counts"]["red"] == 0, rep
    pv = (await client.get(f"{API}/contracts/{cid}/preview", headers=a)).json()
    assert pv["title"] == "PULLIK TIBBIY XIZMAT KO‘RSATISH BO‘YICHA SHARTNOMA № T-15"
    text = "\n".join(s["text"] for s in pv["sections"])
    assert "2 500 000 (ikki million besh yuz ming) so‘mni tashkil etadi" in text
    assert "3 bank ish kuni davomida bank kartasi usulida" in text
    assert "to‘lov summasiga kirmaydi" in text
    assert "— qonunchilik va shartnomada nazarda tutilgan boshqa huquqlar." in text  # empty optional item
    rep = (
        await client.patch(
            f"{API}/contracts/{cid}/answers",
            headers=a,
            json={"answers": {"patient_extra_rights": "ikkinchi shifokor xulosasini olish"}},
        )
    ).json()
    text = "\n".join(
        s["text"] for s in (await client.get(f"{API}/contracts/{cid}/preview", headers=a)).json()["sections"]
    )
    assert "boshqa huquqlar: ikkinchi shifokor xulosasini olish." in text

    v = (await client.post(f"{API}/contracts/{cid}/generate", headers=a, json={})).json()["version"]
    doc = Document(
        io.BytesIO((await client.get(f"{API}/contracts/{cid}/versions/1/download?format=docx", headers=a)).content)
    )
    cells = doc.tables[-1].rows[0].cells
    clinic, patient = cells[0].text, cells[1].text
    assert "MFO: 00974" in clinic and "Rahbar F.I.Sh.: Rahimova Dilnoza" in clinic and "M.O‘." in clinic
    assert "Pasport / ID seriyasi va raqami: AB 7654321" in patient and "MFO" not in patient and "M.O‘." not in patient

    b_phone = "+998937000004"
    await client.post(f"{API}/contracts/{cid}/invite", headers=a, json={"phone": b_phone, "role": "B"})
    b = await login(client, b_phone)
    inv = (await client.get(f"{API}/contracts/invitations", headers=b)).json()
    await client.post(f"{API}/contracts/invitations/{inv[0]['party_id']}/accept", headers=b)
    for h in (a, b):
        await client.post(f"{API}/contracts/{cid}/approve/otp", headers=h)
        r = await client.post(
            f"{API}/contracts/{cid}/approve", headers=h, json={"method": "otp", "code": "123456", "sha256": v["sha256"]}
        )
        assert r.status_code == 200, r.text
    obs = (await client.get(f"{API}/obligations?contract_id={cid}", headers=b)).json()
    pay = next(o for o in obs if o["title"] == "Tibbiy xizmat haqini to‘lash")
    assert pay["due_date"] == _iso(3) and pay["amount"] == "2500000.00"


async def test_medical_dates_rule(client: AsyncClient) -> None:
    h = await login(client, "+998937000005")
    _, rep = await _contract(client, h, "medical_paid", {**MEDICAL, "end_date": _iso(-2)})
    assert {f["rule_code"]: f["severity"] for f in rep["findings"]}["MED_END_BEFORE_START"] == "red"


def test_new_types_are_detected() -> None:
    types = []
    for p in sorted((content_dir() / "contract_types").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        types.append((d["code"], d["detect_keywords"]))
    vehicle = (
        "AVTOTRANSPORT VOSITASINI AYIRBOSHLASH SHARTNOMASI. Birinchi tarafga tegishli bo‘lgan: rusumi Cobalt, "
        "dvigatel raqami B15D2, kuzov raqami XWB3, davlat raqami belgisi 01A123BC. Qayd etish guvohnomasi."
    )
    medical = (
        "PULLIK TIBBIY XIZMAT KO‘RSATISH BO‘YICHA SHARTNOMA. «Tibbiyot muassasasi» «Buyurtmachi»ga pullik tibbiy "
        "xizmat ko‘rsatadi, davolash usullari belgilanadi."
    )
    assert analysis.detect_type(vehicle, types) == "vehicle_exchange"
    assert analysis.detect_type(medical, types) == "medical_paid"
