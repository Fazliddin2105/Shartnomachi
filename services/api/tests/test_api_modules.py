from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.timeutils import today_local, utcnow
from app.db.session import session_scope
from app.modules.audit import service as audit
from app.modules.notifications.models import Notification
from app.modules.obligations.models import Obligation, Reminder, ReminderStatus
from app.modules.reminders.service import run_dispatch_cycle
from tests.conftest import API, EDITOR1, EDITOR2, LAWYER, MODERATOR, login, login_privileged

# --- rules CMS ---------------------------------------------------------------------------


async def test_rule_cms_versioning(client: AsyncClient) -> None:
    e1 = await login_privileged(client, EDITOR1)
    e2 = await login_privileged(client, EDITOR2)
    rule = {
        "code": "TEST_RULE_X",
        "severity": "blue",
        "rule_json": {"field": "answers.x", "op": "gt", "value": 1},
        "message": "x={answers.x}",
        "tests": [{"context": {"answers": {"x": 2}}, "expect": False}],
    }
    r = await client.post(f"{API}/cms/rules", headers=e1, json=rule)
    assert r.json()["error"]["code"] == "rule_tests_failed"
    rule["tests"][0]["expect"] = True
    rid = (await client.post(f"{API}/cms/rules", headers=e1, json=rule)).json()["id"]
    assert (await client.post(f"{API}/cms/rules/{rid}/approve", headers=e1)).json()["error"]["code"] == "four_eyes"
    assert (await client.post(f"{API}/cms/rules/{rid}/approve", headers=e2)).json()["status"] == "approved"
    tried = (
        await client.post(f"{API}/cms/rules/try", headers=e1, json={"rule": rule, "context": {"answers": {"x": 5}}})
    ).json()
    assert tried["triggered"] and tried["findings"][0]["message"] == "x=5"

    # Lex.uz change monitoring: rules citing the act go to review and an editor task is opened
    r = await client.post(f"{API}/cms/rules", headers=e1, json={**rule, "code": "TEST_RULE_LEX", "lex_doc_id": "fk"})
    lex_id = r.json()["id"]
    await client.post(f"{API}/cms/rules/{lex_id}/approve", headers=e2)
    r = await client.post(f"{API}/cms/rules/law-changed", headers=e1, json={"lex_doc_id": "fk"})
    assert r.json()["rules_flagged"] == [lex_id]
    tasks = (await client.get(f"{API}/cms/tasks", headers=e1)).json()
    task = next(t for t in tasks if t["entity_id"] == lex_id)
    assert (await client.post(f"{API}/cms/tasks/{task['id']}/done", headers=e1)).json()["status"] == "done"


# --- calculators ----------------------------------------------------------------------------


async def test_calculators(client: AsyncClient) -> None:
    r = await client.post(f"{API}/calc/deadline", json={"start": "2026-03-19", "days": 1, "kind": "working"})
    assert r.json()["end"] == "2026-03-23"  # Ramazon hayiti + weekend skipped
    r = await client.post(
        f"{API}/calc/penalty",
        json={
            "principal": 1000000,
            "due": "2026-01-01",
            "paid_on": "2026-03-01",
            "rate_percent_per_day": 0.5,
            "max_percent_of_principal": 10,
        },
    )
    assert r.json()["days_overdue"] == 59 and r.json()["amount"] == "100000.00"
    bhm = {d: (await client.get(f"{API}/calc/bhm", params={"on_date": d})).json()["amount"] for d in
           ("2025-01-15", "2026-01-15", "2026-08-31", "2026-09-01", "2026-11-21")}
    assert bhm == {"2025-01-15": "375000.00", "2026-01-15": "412000.00", "2026-08-31": "412000.00",
                   "2026-09-01": "440000.00", "2026-11-21": "440000.00"}  # PF-115: 440 000 from 01.09.2026
    # the removed guide module is really gone
    assert (await client.get(f"{API}/guides")).status_code == 404


# --- scanner ----------------------------------------------------------------------------

CONTRACT_TEXT = """IJARA SHARTNOMASI
1. Shartnoma predmeti
1.1. Ijaraga beruvchi Toshkent shahar, Chilonzor tumani manzilidagi kvartirani Ijarachiga ijaraga beradi.
2. To'lov
2.1. Ijarachi har oy 3 000 000 so'm ijara haqi to'lashga majbur, birinchi to'lov 10.01.2027 gacha.
2.2. Ijaraga beruvchi ijara haqini bir tomonlama oshirishga haqli.
3. Javobgarlik
3.1. Kechiktirilgan har bir kun uchun 1% penya to'lanadi.
3.2. Ijarachi sudga murojaat qilish huquqidan voz kechadi.
"""


async def test_scan_text_report_and_decisions(client: AsyncClient) -> None:
    user = await login(client, "+998941000003")
    r = await client.post(f"{API}/scans/text", headers=user, json={"text": CONTRACT_TEXT})
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["contract_type_code"] == "rent_residential" and scan["type_detected"] is True
    assert scan["risk_level"] == "high"

    rep = (await client.get(f"{API}/scans/{scan['id']}/report", headers=user)).json()
    assert {f["rule_code"] for f in rep["red_clauses"]} == {"CLAUSE_WAIVER_OF_COURT"}
    assert {"CLAUSE_UNILATERAL_CHANGE", "CLAUSE_PENALTY_PER_DAY_HIGH"} <= {f["rule_code"] for f in rep["risky_clauses"]}
    assert any("dates" in f["extracted"] for f in rep["your_obligations"])
    assert any(m["rule_code"] == "MISSING_DISPUTE" for m in rep["missing_elements"])

    card = rep["agree_cards"][0]
    r = await client.post(
        f"{API}/scans/{scan['id']}/findings/{card['finding_id']}/decision", headers=user, json={"decision": "object"}
    )
    assert r.json()["alternative"]

    # "Noto'g'ri xulosa" complaint goes to the moderation queue
    r = await client.post(
        f"{API}/reports",
        headers=user,
        json={"entity": "scan_finding", "entity_id": card["finding_id"], "message": "Bu band menga mos emas"},
    )
    assert r.status_code == 201
    mod = await login(client, MODERATOR)
    assert any(x["id"] == r.json()["id"] for x in (await client.get(f"{API}/reports", headers=mod)).json())

    r = await client.post(f"{API}/scans/{scan['id']}/obligations", headers=user)
    assert len(r.json()["created"]) == 1
    obs = (await client.get(f"{API}/obligations", headers=user)).json()
    assert obs[0]["confirmed"] is False and obs[0]["recurrence_rule"] == "FREQ=MONTHLY"

    other = await login(client, "+998941000004")
    assert (await client.get(f"{API}/scans/{scan['id']}/report", headers=other)).status_code == 404


async def test_scan_upload_background(client: AsyncClient) -> None:
    from app.workers import queue

    user = await login(client, "+998941000005")
    files = {"file": ("shartnoma.txt", CONTRACT_TEXT.encode(), "text/plain")}
    r = await client.post(f"{API}/scans", headers=user, files=files)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    await queue.drain()
    done = (await client.get(f"{API}/scans/{r.json()['id']}", headers=user)).json()
    assert done["status"] == "done" and done["extraction"] == "plain"

    fake = {"file": ("x.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")}
    assert (await client.post(f"{API}/scans", headers=user, files=fake)).json()["error"]["code"] == "file_type"


# --- obligations & reminders -----------------------------------------------------------------


async def test_reminder_dispatch_and_recurrence(client: AsyncClient) -> None:
    user = await login(client, "+998941000006")
    due = today_local() + timedelta(days=1)
    r = await client.post(
        f"{API}/obligations",
        headers=user,
        json={
            "title": "Ijara to'lovi",
            "amount": 3000000,
            "due_date": due.isoformat(),
            "recurrence_rule": "FREQ=MONTHLY",
            "shift_to_working_day": False,
        },
    )
    ob = r.json()
    oid = uuid.UUID(ob["id"])
    async with session_scope() as db:
        rems = (await db.scalars(select(Reminder).where(Reminder.obligation_id == oid))).all()
        assert {x.offset_days for x in rems} <= {1, 0} and {x.channel for x in rems} == {"in_app", "sms"}
        stats = await run_dispatch_cycle(db, now=utcnow() + timedelta(days=3))
        assert stats["sent"] >= 2
    async with session_scope() as db:
        sent = (
            await db.scalars(
                select(Reminder).where(Reminder.obligation_id == oid, Reminder.status == ReminderStatus.SENT)
            )
        ).all()
        assert len(sent) == len(rems)
        notes = (await db.scalars(select(Notification).where(Notification.type == "obligation.reminder"))).all()
        assert any(str(oid) == n.payload["obligation_id"] for n in notes)

    dash = (await client.get(f"{API}/obligations/dashboard", headers=user)).json()
    assert dash["upcoming_30d"] and dash["unpaid_total"]["UZS"] == "3000000.00"

    r = await client.patch(f"{API}/obligations/{oid}", headers=user, json={"status": "done"})
    assert r.json()["status"] == "done"
    async with session_scope() as db:
        series = (
            await db.scalars(select(Obligation).where(Obligation.series_id == oid).order_by(Obligation.occurrence_no))
        ).all()
        assert [o.occurrence_no for o in series] == [1, 2] and series[1].due_date > due
    notifications = (await client.get(f"{API}/notifications", headers=user)).json()
    assert notifications["unread"] >= 1


# --- lawyer archive ----------------------------------------------------------------------------


async def test_case_archive_export(client: AsyncClient) -> None:
    lawyer = await login(client, LAWYER)
    citizen = await login(client, "+998941000007")
    assert (await client.post(f"{API}/cases", headers=citizen, json={"title": "x"})).status_code == 403

    case = (await client.post(f"{API}/cases", headers=lawyer, json={"title": "Ijara nizosi", "tags": ["ijara"]})).json()
    step = (
        await client.post(
            f"{API}/cases/{case['id']}/steps",
            headers=lawyer,
            json={"title": "Talabnoma yuborildi", "description": "Pochta orqali"},
        )
    ).json()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = await client.post(
        f"{API}/cases/{case['id']}/attachments",
        headers=lawyer,
        data={"step_id": step["id"], "note": "kvitansiya"},
        files={"file": ("chek.png", png, "image/png")},
    )
    assert r.status_code == 201 and r.json()["type"] == "image"

    # Attorney-client privilege: the case is invisible to others by default
    assert (await client.get(f"{API}/cases/{case['id']}", headers=citizen)).status_code == 404

    r = await client.get(f"{API}/cases/{case['id']}/export", headers=lawyer)
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["steps"][0]["attachments"][0]["sha256"] == r_sha(png)
    assert "timeline.docx" in zf.namelist() and r.headers["x-manifest-sha256"] == manifest["manifest_sha256"]


def r_sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# --- audit ------------------------------------------------------------------------------------------


async def test_audit_chain_detects_tampering() -> None:
    async with session_scope() as db:
        assert (await audit.verify_chain(db))["ok"] is True
        await db.execute(text("UPDATE audit_log SET action = 'forged' WHERE id = 1"))
        result = await audit.verify_chain(db)
        assert result["ok"] is False and result["broken_at_id"] == 1
        await db.rollback()
