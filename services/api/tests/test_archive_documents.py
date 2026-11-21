"""Personal archive documents: any user files payment receipts / addenda (file optional, owner-only access)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.conftest import API, login

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%test receipt\n"


async def test_citizen_adds_receipt_with_file_and_downloads(client: AsyncClient) -> None:
    h = await login(client, "+998981200001")
    r = await client.post(
        f"{API}/archive/documents",
        headers=h,
        data={
            "title": "Aprel oyi ijara to'lovi cheki",
            "kind": "receipt",
            "description": "Click orqali",
            "amount": "3 000 000",
            "doc_date": "2026-04-05",
        },
        files={"file": ("chek.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["kind_label"] == "To'lov cheki" and d["amount"] == "3000000.00" and d["doc_date"] == "2026-04-05"
    assert d["file"]["name"] == "chek.pdf" and d["file"]["mime"] == "application/pdf" and len(d["file"]["sha256"]) == 64

    listed = (await client.get(f"{API}/archive/documents", headers=h)).json()
    assert [x["id"] for x in listed] == [d["id"]]
    f = await client.get(f"{API}/archive/documents/{d['id']}/file", headers=h)
    assert f.status_code == 200 and f.content == PDF and "chek.pdf" in f.headers["content-disposition"]

    # someone else can neither see nor download nor delete it
    other = await login(client, "+998981200002")
    assert (await client.get(f"{API}/archive/documents", headers=other)).json() == []
    assert (await client.get(f"{API}/archive/documents/{d['id']}/file", headers=other)).status_code == 404
    assert (await client.delete(f"{API}/archive/documents/{d['id']}", headers=other)).status_code == 404

    assert (await client.delete(f"{API}/archive/documents/{d['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/archive/documents", headers=h)).json() == []


async def test_document_without_file_and_validation(client: AsyncClient) -> None:
    h = await login(client, "+998981200003")
    r = await client.post(f"{API}/archive/documents", headers=h, data={"title": "Talabnoma yuborildi", "kind": "claim"})
    assert r.status_code == 201 and r.json()["file"] is None and r.json()["kind_label"] == "Rasmiy talabnoma"
    r = await client.post(
        f"{API}/archive/documents", headers=h, data={"title": "Rasm chek"}, files={"file": ("c.png", PNG, "image/png")}
    )
    assert r.status_code == 201 and r.json()["file"]["mime"] == "image/png"

    bad = [
        ({"title": "x"}, None),  # too short
        ({"title": "Chek", "amount": "uch million"}, None),
        ({"title": "Chek", "kind": "virus"}, None),
        ({"title": "Chek", "archive_id": str(uuid.uuid4())}, None),  # not my archive item
        ({"title": "Chek"}, ("a.txt", b"hello", "text/plain")),  # only PDF / image / DOCX
    ]
    for data, file in bad:
        r = await client.post(f"{API}/archive/documents", headers=h, data=data, files={"file": file} if file else None)
        assert r.status_code in (404, 422), (data, r.status_code, r.text)
