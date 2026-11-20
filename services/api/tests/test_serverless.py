"""Serverless hosting (Vercel): jobs run inside the request; signed DOCX survives a lost disk."""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from docx import Document
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.timeutils import today_local
from app.db.session import session_scope
from app.modules.files.models import StoredFile
from app.modules.files.storage import get_storage
from tests.conftest import API, login

TEXT = (
    "IJARA SHARTNOMASI\n1. Ijaraga beruvchi kvartirani Ijarachiga beradi.\n"
    "2. Ijara haqi oyiga 4 500 000 so'm, har oyning 5-sanasigacha to'lanadi.\n"
)


async def test_inline_jobs_finish_inside_the_request(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "inline_jobs", True)
    h = await login(client, "+998939000001")
    files = {"file": ("ijara.txt", TEXT.encode(), "text/plain")}
    s = (await client.post(f"{API}/scans", headers=h, files=files)).json()
    # no drain(): with inline jobs the upload is fully analysed when the response arrives
    got = (await client.get(f"{API}/scans/{s['id']}", headers=h)).json()
    assert got["status"] == "done" and got["contract_type_code"] == "rent_residential"


async def test_docx_is_rebuilt_when_the_stored_file_is_gone(client: AsyncClient) -> None:
    h = await login(client, "+998939000002")
    today = today_local()
    c = (await client.post(f"{API}/contracts", headers=h, json={"type_code": "loan", "my_role": "A"})).json()
    await client.patch(
        f"{API}/contracts/{c['id']}/answers",
        headers=h,
        json={
            "answers": {
                "party_a": {"name": "Aliyev Vali"},
                "party_b": {"name": "Karimov Sardor"},
                "city": "Toshkent",
                "contract_date": today.isoformat(),
                "amount": 5_000_000,
                "currency": "UZS",
                "given_date": today.isoformat(),
                "return_date": (today + timedelta(days=30)).isoformat(),
            }
        },
    )
    v = (await client.post(f"{API}/contracts/{c['id']}/generate", headers=h, json={})).json()["version"]
    async with session_scope() as db:
        row = await db.get(StoredFile, __import__("uuid").UUID(v["file_id"]))
        assert row is not None
        await get_storage().delete(row.storage_key)  # simulate an ephemeral disk being wiped
    dl = await client.get(f"{API}/contracts/{c['id']}/versions/1/download?format=docx", headers=h)
    assert dl.status_code == 200 and dl.headers["x-content-sha256"] == v["sha256"]
    text = "\n".join(p.text for p in Document(io.BytesIO(dl.content)).paragraphs)
    assert "QARZ SHARTNOMASI" in text and "Aliyev Vali" in text


async def test_web_folder_never_serves_code_or_databases(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    from app.main import create_app

    (tmp_path / "index.html").write_text("<html>Huquqiy</html>", encoding="utf-8")
    (tmp_path / "server.py").write_text("SECRET = 1", encoding="utf-8")
    (tmp_path / "huquqiy_platforma.db").write_bytes(b"SQLite format 3")
    (tmp_path / ".env").write_text("KEY=1", encoding="utf-8")
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "frontend_dir", str(tmp_path))
    app = create_app()
    async with Client(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/")).status_code == 200
        assert (await c.get("/js/app.js")).status_code == 200
        for p in ("/server.py", "/huquqiy_platforma.db", "/.env"):
            assert (await c.get(p)).status_code == 404, p
