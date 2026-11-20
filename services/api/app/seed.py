"""Idempotent loader for `packages/legal-content` (+ optional dev users).

    python -m app.seed                # reference data (BHM, calendar), contract types, clauses, rules
    python -m app.seed --dev-users    # also create admin/editor/lawyer accounts (dev only)

Rules are loaded as *approved* only in dev/test, marked
`meta.demo = true`; in staging/prod they are loaded as drafts and must go
through the expert approval workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.timeutils import utcnow
from app.db.session import init_engine, session_scope
from app.modules.calc.models import BhmRate, CalendarDay, DayKind
from app.modules.contracts.models import ClauseLibrary, ContractType, FormRequirement
from app.modules.rules.models import LegalRule, RuleStatus
from app.modules.rules.service import check_definition
from app.modules.users.models import Profile, ProfileType, User, UserRole

log = logging.getLogger("seed")


def content_dir() -> Path:
    p = Path(get_settings().legal_content_dir)
    if not p.is_absolute():
        p = (Path(__file__).resolve().parents[1] / p).resolve()
    return p


def _load(rel: str) -> Any:
    return json.loads((content_dir() / rel).read_text(encoding="utf-8"))


async def seed_reference(db: AsyncSession) -> None:
    ref = _load("seed/reference.json")
    for r in ref["bhm_rates"]:
        d = date.fromisoformat(r["valid_from"])
        if not await db.scalar(select(BhmRate.id).where(BhmRate.valid_from == d)):
            db.add(BhmRate(amount=Decimal(str(r["amount"])), valid_from=d, legal_ref=r.get("legal_ref")))
    for r in ref["calendar_2026"]:
        d = date.fromisoformat(r["day"])
        if await db.get(CalendarDay, d) is None:
            db.add(CalendarDay(day=d, kind=DayKind(r["kind"]), title=r.get("title")))
    await db.flush()


async def seed_contract_types(db: AsyncSession) -> dict[str, ContractType]:
    out: dict[str, ContractType] = {}
    for path in sorted((content_dir() / "contract_types").glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        row = await db.scalar(select(ContractType).where(ContractType.code == d["code"]))
        if row is not None and (row.source or {}).get("kind") == "lexuz":
            # Official lex.uz template is managed by the import/approval pipeline — never overwrite it here.
            out[d["code"]] = row
            continue
        if row is None:
            row = ContractType(code=d["code"])
            db.add(row)
        for k in (
            "title_uz",
            "title_ru",
            "description",
            "form_rules",
            "questionnaire",
            "template",
            "required_elements",
            "obligation_templates",
            "legal_refs",
            "detect_keywords",
        ):
            setattr(row, k, d.get(k) if d.get(k) is not None else getattr(row, k))
        row.template_ru = d.get("template_ru")
        if d.get("source"):
            row.source = d["source"]
        row.form_requirement = FormRequirement(d.get("form_requirement", "simple"))
        out[d["code"]] = row
    await db.flush()
    for c in _load("clauses/library.json")["clauses"]:
        row = await db.scalar(
            select(ClauseLibrary).where(ClauseLibrary.code == c["code"], ClauseLibrary.contract_type_id.is_(None))
        )
        if row is None:
            db.add(ClauseLibrary(**c))
        else:
            for k, v in c.items():
                setattr(row, k, v)
    await db.flush()
    return out


async def seed_rules(db: AsyncSession, types: dict[str, ContractType], *, approve: bool) -> int:
    n = 0
    for r in _load("rules/rules.json")["rules"]:
        if await db.scalar(select(LegalRule.id).where(LegalRule.code == r["code"])):
            continue
        payload = {
            k: r.get(k)
            for k in (
                "code",
                "scope",
                "severity",
                "rule_json",
                "message",
                "fix_suggestion",
                "law_ref",
                "lex_url",
                "lex_doc_id",
                "category",
            )
        }
        payload["tests"] = r.get("tests", [])
        check_definition(payload)  # seed content must pass its own tests
        ct = r.get("contract_type")
        db.add(
            LegalRule(
                **payload,
                version=1,
                contract_type_id=types[ct].id if ct else None,
                status=RuleStatus.APPROVED if approve else RuleStatus.DRAFT,
                approved_at=utcnow() if approve else None,
                meta={
                    "demo": True,
                    "source": "legal-content",
                    **({"autofix": r["autofix"]} if r.get("autofix") else {}),
                },
            )
        )
        n += 1
    await db.flush()
    return n


DEV_USERS = [
    ("+998900000001", UserRole.ADMIN, "Admin"),
    ("+998900000002", UserRole.EDITOR, "Muharrir 1"),
    ("+998900000003", UserRole.EDITOR, "Muharrir 2"),
    ("+998900000004", UserRole.LAWYER, "Yurist"),
    ("+998900000005", UserRole.MODERATOR, "Moderator"),
]


async def seed_dev_users(db: AsyncSession) -> None:
    for phone, role, name in DEV_USERS:
        if await db.scalar(select(User.id).where(User.phone == phone)):
            continue
        u = User(phone=phone, role=role, consent_at=utcnow())
        u.profile = Profile(
            full_name=name,
            type=ProfileType.LAWYER if role == UserRole.LAWYER else ProfileType.PERSON,
            license_no="DEMO-0001" if role == UserRole.LAWYER else None,
            license_verified_at=utcnow() if role == UserRole.LAWYER else None,
        )
        db.add(u)
    await db.flush()


async def run(dev_users: bool = False) -> dict[str, int]:
    s = get_settings()
    demo_live = s.is_dev
    async with session_scope() as db:
        await seed_reference(db)
        types = await seed_contract_types(db)
        rules_n = await seed_rules(db, types, approve=demo_live)
        if dev_users:
            if not s.is_dev:
                raise SystemExit("--dev-users is allowed only in dev/test")
            await seed_dev_users(db)
    return {
        "contract_types": len(types),
        "rules_added": rules_n,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-users", action="store_true")
    args = parser.parse_args()
    configure_logging()
    init_engine()
    result = asyncio.run(run(dev_users=args.dev_users))
    log.info("seed complete: %s", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
