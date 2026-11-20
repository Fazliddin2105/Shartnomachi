"""Two-party negotiation: own fields, objections/counter-offers, consent -> common contract, archive, cleanup."""

from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient

from app.core.timeutils import today_local
from tests.conftest import API, login

TODAY = today_local()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


A_TERMS = {
    "city": "Samarqand sh.",
    "contract_date": TODAY.isoformat(),
    "party_a": {"name": "Rahimov Bobur", "address": "Samarqand", "tin": "31205941230042", "phone": "+998901234567"},
    "party_b": {"name": "Tursunova Malika"},  # prefilled by A before B joins — allowed
    "property_address": "Samarqand sh., Registon 15",
    "property_area": 64,
    "rooms": 3,
    "purpose": "yashash",
    "start_date": _iso(1),
    "end_date": _iso(200),
    "rent_amount": 3_000_000,
    "payment_day": 10,
    "payment_method": "cash",
    "utilities": "tenant",
    "handover_days": 2,
    "sale_notice_days": 30,
    "copies": 2,
}


async def _types(client: AsyncClient, h: dict) -> list[str]:
    return [n["type"] for n in (await client.get(f"{API}/notifications", headers=h)).json()["items"]]


async def _setup(client: AsyncClient, a_phone: str, b_phone: str) -> tuple[dict, dict, str]:
    a = await login(client, a_phone)
    b = await login(client, b_phone)
    c = (await client.post(f"{API}/contracts", headers=a, json={"type_code": "rent_private", "my_role": "A"})).json()
    r = await client.patch(f"{API}/contracts/{c['id']}/answers", headers=a, json={"answers": A_TERMS})
    assert r.status_code == 200, r.text
    await client.post(f"{API}/contracts/{c['id']}/invite", headers=a, json={"phone": b_phone, "role": "B"})
    inv = (await client.get(f"{API}/contracts/invitations", headers=b)).json()
    assert (await client.post(f"{API}/contracts/invitations/{inv[0]['party_id']}/accept", headers=b)).status_code == 200
    return a, b, c["id"]


async def test_full_negotiation_to_signed_archive(client: AsyncClient) -> None:
    a, b, cid = await _setup(client, "+998936000001", "+998936000002")
    url = f"{API}/contracts/{cid}"

    # each side edits only its own data once both are in
    r = await client.patch(f"{url}/answers", headers=a, json={"answers": {"party_b.name": "Boshqa ism"}})
    assert r.status_code == 403 and r.json()["error"]["details"]["fields"] == ["party_b.name"]
    r = await client.patch(f"{url}/answers", headers=b, json={"answers": {"party_a.name": "X"}})
    assert r.json()["error"]["code"] == "field_not_yours"

    st = (await client.get(f"{url}/negotiation", headers=b)).json()
    assert st["my_side"] == "B" and st["next_action"] == "fill_your_data"
    assert set(st["missing_by_side"]["B"]) == {"party_b.address", "party_b.tin", "party_b.phone"}
    editable = {f["key"]: f["editable"] for f in st["fields"]}
    assert editable["party_b.tin"] and not editable["party_a.tin"] and editable["rent_amount"]

    r = await client.patch(
        f"{url}/answers",
        headers=b,
        json={
            "answers": {
                "party_b.address": "Samarqand",
                "party_b.tin": "31205941230043",
                "party_b.phone": "+998907654321",
            }
        },
    )
    assert r.status_code == 200 and r.json()["ready"] is True
    assert (await client.get(f"{url}/negotiation", headers=b)).json()["next_action"] == "agree"

    # B disagrees with the rent and proposes a lower one
    o = await client.post(
        f"{url}/objections",
        headers=b,
        json={
            "comment": "Ijara haqi bozor narxidan yuqori, 2,5 mln taklif qilaman",
            "proposed": {"rent_amount": 2500000},
        },
    )
    assert o.status_code == 201, o.text
    oid = o.json()["id"]
    assert "contract.objection" in await _types(client, a)
    assert (await client.get(f"{url}/negotiation", headers=a)).json()["next_action"] == "resolve_objections"
    r = await client.post(f"{url}/objections/{oid}/accept", headers=b)
    assert r.json()["error"]["code"] == "own_objection"  # the other side decides

    r = await client.post(f"{url}/objections/{oid}/accept", headers=a, json={"note": "Kelishdik"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert (await client.get(url, headers=a)).json()["answers"]["rent_amount"] == 2500000
    assert "contract.objection_accepted" in await _types(client, b)

    # no common contract without both consents
    r = await client.post(f"{url}/generate", headers=a, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "agreement_required"

    r = (await client.post(f"{url}/agree", headers=a)).json()
    assert r["waiting_for"] == ["B"] and r["generated"] is None
    # a later change of terms voids consents
    await client.patch(f"{url}/answers", headers=b, json={"answers": {"party_b.address": "Samarqand, Siyob 4"}})
    st = (await client.get(f"{url}/negotiation", headers=a)).json()
    assert not any(p["agreed"] for p in st["parties"]) and st["next_action"] == "agree"
    assert "contract.terms_changed" in await _types(client, a)

    await client.post(f"{url}/agree", headers=a)
    r = (await client.post(f"{url}/agree", headers=b)).json()
    assert r["waiting_for"] == [] and r["generated"]["number"] == 1  # common contract produced for both
    sha = r["generated"]["sha256"]
    for h in (a, b):
        assert "contract.ready_to_sign" in await _types(client, h)
        assert (await client.get(f"{url}/negotiation", headers=h)).json()["next_action"] == "sign"

    for h in (a, b):
        await client.post(f"{url}/approve/otp", headers=h)
        r = await client.post(f"{url}/approve", headers=h, json={"method": "otp", "code": "123456", "sha256": sha})
        assert r.status_code == 200, r.text
    assert r.json()["contract_status"] == "active"

    # both have it in their personal archive
    for h, side, other in ((a, "A", "Tursunova Malika"), (b, "B", "Rahimov Bobur")):
        items = (await client.get(f"{API}/archive", headers=h)).json()
        assert len(items) == 1 and items[0]["side"] == side and items[0]["counterparty"] == other
        assert items[0]["sha256"] == sha and items[0]["total_amount"] == "2500000.00"
        d = (await client.get(f"{API}/archive/{items[0]['id']}", headers=h)).json()
        assert d["integrity"]["intact"] is True and len(d["signatures"]) == 2
    item = (await client.get(f"{API}/archive", headers=a)).json()[0]
    p = await client.patch(f"{API}/archive/{item['id']}", headers=a, json={"note": "Asl nusxa seyfda", "tags": ["uy"]})
    assert p.json()["note"] == "Asl nusxa seyfda" and p.json()["tags"] == ["uy"]
    assert (await client.get(f"{API}/archive/{item['id']}", headers=b)).status_code == 404  # private per user

    kinds = [e["kind"] for e in (await client.get(f"{url}/timeline", headers=a)).json()]
    for k in (
        "created",
        "invited",
        "joined",
        "terms_changed",
        "objection",
        "objection_accepted",
        "agreed",
        "generated",
        "signed",
        "activated",
    ):
        assert k in kinds, k
    # a signed contract can't be deleted
    r = await client.delete(url, headers=a)
    assert r.json()["error"]["code"] == "contract_signed"


async def test_illegal_terms_can_not_be_agreed_or_generated(client: AsyncClient) -> None:
    h = await login(client, "+998936000003")
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})).json()
    bad = {
        "party_a": {"name": "Aliyev Vali"},
        "party_b": {"name": "Karimov Sardor"},
        "city": "Toshkent",
        "contract_date": TODAY.isoformat(),
        "amount": 1_000_000,
        "currency": "UZS",
        "given_date": TODAY.isoformat(),
        "return_date": _iso(-3),
    }
    r = (await client.patch(f"{API}/contracts/{c['id']}/answers", headers=h, json={"answers": bad})).json()
    assert r["summary"]["blocking"] is True
    assert "return_date" in r["field_warnings"]  # live warning next to the field
    g = await client.post(f"{API}/contracts/{c['id']}/generate", headers=h, json={"acknowledge_red": True})
    assert g.status_code == 422 and g.json()["error"]["code"] == "illegal_clauses"  # no override any more
    ag = await client.post(f"{API}/contracts/{c['id']}/agree", headers=h)
    assert ag.json()["error"]["code"] == "illegal_clauses"
    assert (await client.get(f"{API}/contracts/{c['id']}/negotiation", headers=h)).json()["next_action"] in (
        "fix_illegal_terms",
        "fill_your_data",
    )


async def test_objection_after_generation_reopens_negotiation(client: AsyncClient) -> None:
    a = await login(client, "+998936000004")
    b_phone = "+998936000005"
    c = (await client.post(f"{API}/contracts", headers=a, json={"type_code": "rent_private", "my_role": "A"})).json()
    full = {
        **A_TERMS,
        "party_b": {
            "name": "Tursunova Malika",
            "address": "Samarqand",
            "tin": "31205941230043",
            "phone": "+998907654321",
        },
    }
    await client.patch(f"{API}/contracts/{c['id']}/answers", headers=a, json={"answers": full})
    assert (await client.post(f"{API}/contracts/{c['id']}/generate", headers=a, json={})).status_code == 200  # solo
    await client.post(f"{API}/contracts/{c['id']}/invite", headers=a, json={"phone": b_phone, "role": "B"})
    b = await login(client, b_phone)
    inv = (await client.get(f"{API}/contracts/invitations", headers=b)).json()
    await client.post(f"{API}/contracts/invitations/{inv[0]['party_id']}/accept", headers=b)
    assert (await client.get(f"{API}/contracts/{c['id']}/negotiation", headers=b)).json()["next_action"] == "sign"

    o = await client.post(
        f"{API}/contracts/{c['id']}/objections",
        headers=b,
        json={"comment": "Kommunal to'lovlar ijara haqiga kirsin", "proposed": {"utilities": "included"}},
    )
    assert o.status_code == 201
    got = (await client.get(f"{API}/contracts/{c['id']}", headers=a)).json()
    assert got["status"] == "draft"  # back to negotiation, a new version will follow
    r = await client.post(f"{API}/contracts/{c['id']}/objections/{o.json()['id']}/withdraw", headers=b)
    assert r.json()["status"] == "withdrawn"
    bad = await client.post(
        f"{API}/contracts/{c['id']}/objections", headers=b, json={"comment": "noma'lum", "fields": ["no_such_field"]}
    )
    assert bad.json()["error"]["code"] == "unknown_fields"


async def test_housekeeping_delete_cancel_rename_revoke_duplicate_clear(client: AsyncClient) -> None:
    h = await login(client, "+998936000006")
    c1 = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})).json()
    r = await client.delete(f"{API}/contracts/{c1['id']}", headers=h)
    assert r.json() == {"deleted": True, "status": None}
    assert (await client.get(f"{API}/contracts/{c1['id']}", headers=h)).status_code == 404

    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "rent_private", "my_role": "A"})).json()
    url = f"{API}/contracts/{c['id']}"
    full = {
        **A_TERMS,
        "party_b": {
            "name": "Tursunova Malika",
            "address": "Samarqand",
            "tin": "31205941230043",
            "phone": "+998907654321",
        },
    }
    await client.patch(f"{url}/answers", headers=h, json={"answers": full})
    # clearing a field removes it (and makes it missing again)
    r = (await client.patch(f"{url}/answers", headers=h, json={"answers": {"party_a.phone": None}})).json()
    assert "party_a.phone" in r["missing_fields"]
    assert "phone" not in (await client.get(url, headers=h)).json()["answers"]["party_a"]
    await client.patch(f"{url}/answers", headers=h, json={"answers": {"party_a.phone": "+998901234567"}})

    assert (await client.patch(url, headers=h, json={"title": "Registon 15 ijarasi"})).json()[
        "title"
    ] == "Registon 15 ijarasi"
    await client.post(f"{url}/invite", headers=h, json={"phone": "+998936000007", "role": "B"})
    b_party = next(p for p in (await client.get(url, headers=h)).json()["parties"] if p["role"] == "B")
    assert (await client.delete(f"{url}/parties/{b_party['id']}/invitation", headers=h)).status_code == 204
    invitee = await login(client, "+998936000007")
    assert (await client.get(f"{API}/contracts/invitations", headers=invitee)).json() == []

    dup = await client.post(f"{url}/duplicate", headers=h)
    assert dup.status_code == 201 and dup.json()["title"].endswith("(yangi)")
    dup_answers = (await client.get(f"{API}/contracts/{dup.json()['id']}", headers=h)).json()["answers"]
    assert dup_answers["rent_amount"] == 3_000_000 and dup_answers["party_a"]["name"] == "Rahimov Bobur"

    assert (await client.post(f"{url}/generate", headers=h, json={})).status_code == 200
    r = await client.delete(url, headers=h)
    assert r.json() == {"deleted": False, "status": "cancelled"}  # versions exist: kept as evidence


async def test_cleanup_obligations_scans_notifications(client: AsyncClient) -> None:
    h = await login(client, "+998936000008")
    ob = (
        await client.post(f"{API}/obligations", headers=h, json={"title": "Soliq hisoboti", "due_date": _iso(10)})
    ).json()
    assert (await client.patch(f"{API}/obligations/{ob['id']}", headers=h, json={"status": "done"})).json()[
        "status"
    ] == "done"
    back = (await client.patch(f"{API}/obligations/{ob['id']}", headers=h, json={"status": "pending"})).json()
    assert back["status"] == "pending" and back["completed_at"] is None
    assert (await client.delete(f"{API}/obligations/{ob['id']}", headers=h)).status_code == 204
    assert all(o["id"] != ob["id"] for o in (await client.get(f"{API}/obligations", headers=h)).json())

    text = "IJARA SHARTNOMASI\n1. Ijaraga beruvchi kvartirani Ijarachiga beradi.\n2. Ijara haqi oyiga 4 500 000 so'm to'lanadi."
    s = (await client.post(f"{API}/scans/text", headers=h, json={"text": text})).json()
    assert (await client.delete(f"{API}/scans/{s['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/scans/{s['id']}", headers=h)).status_code == 404

    n = (await client.get(f"{API}/notifications", headers=h)).json()
    if n["items"]:
        assert (await client.delete(f"{API}/notifications/{n['items'][0]['id']}", headers=h)).status_code == 204
    await client.post(f"{API}/notifications/read", headers=h, json=None)
    assert (await client.delete(f"{API}/notifications", headers=h)).status_code == 204
    assert (await client.get(f"{API}/notifications", headers=h)).json()["items"] == []
