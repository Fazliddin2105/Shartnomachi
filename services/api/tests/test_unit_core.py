"""Pure unit tests: rule engine, safe expressions, calendar, reminder planner, crypto, scan text pipeline."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.ai.pii import mask, unmask
from app.core import crypto, safe_expr
from app.core.errors import ValidationFailed
from app.core.timeutils import WorkCalendar
from app.modules.reminders import planner
from app.modules.rules import engine
from app.modules.scan import analysis

# --- rule engine ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cond", "ctx", "expected"),
    [
        ({"field": "a.x", "op": "gt", "value": 3}, {"a": {"x": 4}}, True),
        ({"field": "a.x", "op": "gt", "value": 3}, {"a": {"x": "3,5"}}, True),
        ({"field": "a.x", "op": "gt", "value": 3}, {"a": {}}, False),
        ({"field": "a.x", "op": "missing"}, {"a": {"x": ""}}, True),
        ({"field": "a.x", "op": "in", "value": ["USD"]}, {"a": {"x": "USD"}}, True),
        (
            {"field": "a.d2", "op": "lte", "value": {"field": "a.d1"}},
            {"a": {"d1": "2026-05-01", "d2": "2026-04-30"}},
            True,
        ),
        (
            {"field": "a.d2", "op": "lte", "value": {"field": "a.d1"}},
            {"a": {"d1": "2026-05-01", "d2": "2026-06-01"}},
            False,
        ),
        ({"op": "expr", "value": "a__dep > a__rent * 3"}, {"a": {"dep": 400, "rent": 100}}, True),
        ({"op": "expr", "value": "a__unknown > 1"}, {"a": {}}, False),
        (
            {"all": [{"field": "x", "op": "eq", "value": 1}, {"not": {"field": "y", "op": "eq", "value": 2}}]},
            {"x": 1, "y": 3},
            True,
        ),
        (
            {"any": [{"field": "x", "op": "eq", "value": 5}, {"field": "y", "op": "regex", "value": "^ab"}]},
            {"x": 1, "y": "ABC"},
            True,
        ),
        (
            {"field": "t", "op": "number_in_text_gt", "value": 0.5, "pattern": r"(\d+(?:[.,]\d+)?)\s*%"},
            {"t": "kuniga 0,7% penya"},
            True,
        ),
    ],
)
def test_engine_conditions(cond: dict, ctx: dict, expected: bool) -> None:
    assert engine.evaluate(cond, ctx) is expected


def test_engine_validation_rejects_bad_rules() -> None:
    with pytest.raises(engine.RuleError):
        engine.validate_condition({"field": "x", "op": "nope"})
    with pytest.raises(engine.RuleError):
        engine.validate_condition({"field": "x", "op": "regex", "value": "("})
    with pytest.raises(engine.RuleError):
        engine.validate_condition({"all": []})


def test_engine_findings_sorted_and_rendered() -> None:
    rules = [
        engine.Rule.from_json(
            {
                "code": "B",
                "severity": "yellow",
                "when": {"field": "answers.p", "op": "gt", "value": 0.5},
                "message": "Penya {answers.p}%",
            }
        ),
        engine.Rule.from_json(
            {
                "code": "A",
                "severity": "red",
                "when": {"field": "answers.m", "op": "gt", "value": 3},
                "message": "Sinov {answers.m} oy",
            }
        ),
    ]
    out = engine.run_answers(rules, {"answers": {"p": 1, "m": 6}})
    assert [f.rule_code for f in out] == ["A", "B"]
    assert out[0].message == "Sinov 6 oy" and out[0].fields == ("answers.m",)
    assert engine.summarize(out) == {"counts": {"red": 1, "yellow": 1, "blue": 0}, "blocking": True}


def test_engine_clause_category_filter() -> None:
    rule = engine.Rule.from_json(
        {
            "code": "P",
            "severity": "yellow",
            "scope": "clause",
            "category": "penalty",
            "when": {"field": "clause.text", "op": "contains", "value": "penya"},
            "message": "m",
        }
    )
    clauses = [{"index": 0, "text": "penya", "category": "price"}, {"index": 1, "text": "penya", "category": "penalty"}]
    assert [f.clause_index for f in engine.run_clauses([rule], clauses, {})] == [1]


# --- safe expressions --------------------------------------------------------------------


def test_safe_expr() -> None:
    assert safe_expr.evaluate("max(amount * 0.02, bhm)", {"amount": 10_000_000, "bhm": 375_000}) == 375_000
    assert safe_expr.evaluate("round(bhm * 0.333, 2)", {"bhm": 100}) == 33.3
    assert safe_expr.evaluate("1 if x > 2 else 0", {"x": 3}) == 1


@pytest.mark.parametrize(
    "expr", ["__import__('os')", "bhm.__class__", "open('x')", "[1,2]", "2 ** 100", "1/0", "y + 1"]
)
def test_safe_expr_rejects(expr: str) -> None:
    with pytest.raises(ValidationFailed):
        safe_expr.evaluate(expr, {"bhm": 1})


# --- calendar & reminders --------------------------------------------------------------------


def test_working_days_with_holidays() -> None:
    cal = WorkCalendar.build(holidays=[date(2026, 3, 20)], work_week=[0, 1, 2, 3, 4])
    # Thu 2026-03-19 + 1 working day: Fri 20 is a holiday, Sat/Sun weekend -> Mon 23
    assert cal.add_working_days(date(2026, 3, 19), 1) == date(2026, 3, 23)
    # calendar term ending on Saturday shifts to Monday
    assert cal.add_calendar_days(date(2026, 3, 14), 7) == date(2026, 3, 23)
    assert cal.working_days_between(date(2026, 3, 16), date(2026, 3, 23)) == 4


def test_reminder_plan_offsets_and_past() -> None:
    # now = 2026-06-10 10:00 Tashkent (05:00 UTC); due 2026-06-12
    now = datetime(2026, 6, 10, 5, 0, tzinfo=UTC)
    plan = planner.plan(due=date(2026, 6, 12), offsets=[6, 3, 2, 1, 0], send_hour=9, now=now)
    # 6 and 3 days before are in the past; 2 days before is "today" but past 09:00 -> fires now
    assert [p.offset_days for p in plan] == [2, 1, 0]
    assert plan[0].scheduled_at == now
    assert plan[1].scheduled_at == datetime(2026, 6, 11, 4, 0, tzinfo=UTC)  # 09:00 Tashkent
    assert planner.plan(due=date(2026, 6, 1), offsets=[0], send_hour=9, now=now) == []


def test_rrule_next_occurrence() -> None:
    assert planner.next_occurrence("FREQ=MONTHLY;BYMONTHDAY=10", after=date(2026, 1, 10)) == date(2026, 2, 10)
    assert (
        planner.next_occurrence("FREQ=MONTHLY;BYMONTHDAY=10", after=date(2026, 1, 10), until=date(2026, 1, 31)) is None
    )


# --- crypto --------------------------------------------------------------------------------


def test_envelope_encryption_and_tamper_detection() -> None:
    blob = crypto.encrypt_blob(b"secret contract", aad=b"file-1")
    assert crypto.decrypt_blob(blob.ciphertext, blob.wrapped_key, aad=b"file-1") == b"secret contract"
    with pytest.raises(Exception):
        crypto.decrypt_blob(blob.ciphertext, blob.wrapped_key, aad=b"file-2")
    tampered = blob.ciphertext[:-1] + bytes([blob.ciphertext[-1] ^ 1])
    with pytest.raises(Exception):
        crypto.decrypt_blob(tampered, blob.wrapped_key, aad=b"file-1")
    assert crypto.decrypt_field(crypto.encrypt_field("12345678901234")) == "12345678901234"


def test_canonical_hash_is_order_independent() -> None:
    a = crypto.sha256_hex(crypto.canonical_json({"b": 1, "a": [1, 2]}))
    b = crypto.sha256_hex(crypto.canonical_json({"a": [1, 2], "b": 1}))
    assert a == b


# --- scan pipeline & PII ----------------------------------------------------------------------

SAMPLE = """QARZ SHARTNOMASI
1. Shartnoma predmeti
1.1. Qarz beruvchi 10 000 000 so'm qarz beradi.
1.2. Qarz oluvchi pulni 01.09.2026 gacha qaytarishga majbur.
2. Javobgarlik
2.1. Kechiktirilgan har bir kun uchun 1% penya to'lanadi.
"""


def test_segmentation_and_extraction() -> None:
    clauses = analysis.segment(analysis.clean_text(SAMPLE))
    texts = [c.text for c in clauses]
    assert any(t.startswith("1.2.") for t in texts)
    c12 = next(c for c in clauses if c.text.startswith("1.2."))
    assert analysis.duty_or_right(c12.text) == "duty"
    assert analysis.extract(c12.text)["dates"] == ["2026-09-01"]
    amounts = analysis.extract(next(c for c in clauses if c.text.startswith("1.1.")).text)["amounts"]
    assert amounts == [{"value": 10_000_000.0, "currency": "UZS"}]
    assert analysis.classify("Kechiktirilgan har bir kun uchun 1% penya") == "penalty"


def test_pii_masking_roundtrip() -> None:
    text = "Aliyev Vali Karimovich, JShShIR 31234567890123, tel +998 90 123 45 67, a@b.uz"
    masked, mapping = mask(text)
    assert "31234567890123" not in masked and "a@b.uz" not in masked and "Karimovich" not in masked
    assert unmask(masked, mapping) == text


def test_db_transaction_commits_before_response() -> None:
    """Regression: with the default «request» scope the commit ran after the response was sent, so a fast
    client could verify an OTP / refresh a token before the previous request's data was committed."""
    from typing import get_args

    from app.api.deps import DB

    assert get_args(DB)[1].scope == "function"


def test_hosted_postgres_url_is_normalized_for_asyncpg() -> None:
    from app.core.config import normalize_db_url

    neon = "postgres://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert (
        normalize_db_url(neon) == "postgresql+asyncpg://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?ssl=require"
    )
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert normalize_db_url("sqlite+aiosqlite:///./x.db") == "sqlite+aiosqlite:///./x.db"
