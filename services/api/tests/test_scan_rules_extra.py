from __future__ import annotations

from httpx import AsyncClient

from app.modules.scan.analysis import classify
from tests.conftest import API, login

RENT = """IJARA SHARTNOMASI
1. Ijaraga beruvchi Toshkent sh., Chilonzor 5 manzilidagi kvartirani Ijarachiga beradi.
2. Ijara haqi oyiga 4 500 000 so'm, har oyning 5-sanasigacha to'lanadi.
3. To'lov kechiktirilsa kuniga 1.5% penya to'lanadi.
4. Ijaraga beruvchi shartnomani 24 soat ichida ogohlantirishsiz bekor qilishi mumkin.
"""


def test_penalty_wins_over_price_keywords() -> None:
    assert classify("To'lov kechiktirilsa kuniga 1.5% penya to'lanadi.") == "penalty"
    assert classify("Xizmat narxi 4 500 000 so'm.") == "price"


async def test_scan_flags_high_daily_penalty_and_no_notice_termination(client: AsyncClient) -> None:
    h = await login(client, "+998933000001")
    scan = (await client.post(f"{API}/scans/text", headers=h, json={"text": RENT})).json()
    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=h)).json()
    codes = {f["rule_code"] for f in rep["risky_clauses"] + rep["red_clauses"]}
    assert {"CLAUSE_PENALTY_PER_DAY_HIGH", "CLAUSE_TERMINATION_NO_NOTICE"} <= codes


async def test_selected_clauses_shape_is_validated(client: AsyncClient) -> None:
    h = await login(client, "+998933000002")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})).json()
    r = await client.patch(
        f"{API}/contracts/{c['id']}/answers", headers=h, json={"answers": {}, "selected_clauses": [{"code": "x"}]}
    )
    assert r.status_code == 422
