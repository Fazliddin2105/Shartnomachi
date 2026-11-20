from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.timeutils import utcnow
from app.modules.audit import service as audit
from app.modules.moderation.models import ContentTask
from app.modules.rules import engine
from app.modules.rules.models import LegalRule, RuleStatus
from app.modules.users.models import User

_EXECUTABLE = (RuleStatus.APPROVED, RuleStatus.NEEDS_REVIEW)


def to_engine(row: LegalRule) -> engine.Rule:
    return engine.Rule(
        code=row.code,
        severity=row.severity,
        when=row.rule_json,
        message=row.message,
        scope=row.scope,
        law_ref=row.law_ref,
        lex_url=row.lex_url,
        fix_suggestion=row.fix_suggestion,
        category=row.category,
        version=row.version,
        autofix=(row.meta or {}).get("autofix"),
    )


async def active_rules(db: AsyncSession, contract_type_id: uuid.UUID | None) -> list[engine.Rule]:
    """Approved rules for a contract type plus the global ones."""
    cond = LegalRule.contract_type_id.is_(None)
    if contract_type_id is not None:
        cond = or_(cond, LegalRule.contract_type_id == contract_type_id)
    rows = await db.scalars(select(LegalRule).where(cond, LegalRule.status.in_(_EXECUTABLE)))
    return [to_engine(r) for r in rows]


def check_definition(data: dict[str, Any]) -> engine.Rule:
    try:
        rule = engine.Rule.from_json({**data, "when": data["rule_json"]})
    except (engine.RuleError, KeyError, ValueError) as e:
        raise ValidationFailed(f"Invalid rule: {e}", code="rule_invalid") from e
    failures = [r for r in engine.run_tests(rule, data.get("tests") or []) if not r["passed"]]
    if failures:
        raise ValidationFailed("Rule tests failed", code="rule_tests_failed", details=failures)
    return rule


async def create_draft(db: AsyncSession, data: dict[str, Any], author: User) -> LegalRule:
    data = dict(data)
    autofix = data.pop("autofix", None)
    check_definition(data)
    latest = await db.scalar(
        select(LegalRule).where(LegalRule.code == data["code"]).order_by(LegalRule.version.desc()).limit(1)
    )
    if latest is not None and latest.status == RuleStatus.DRAFT:
        raise Conflict("A draft for this rule already exists; edit it instead", code="rule_draft_exists")
    row = LegalRule(
        **data,
        meta={"autofix": autofix} if autofix else {},
        version=(latest.version + 1) if latest else 1,
        status=RuleStatus.DRAFT,
        author_id=author.id,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        action="rule.draft",
        entity="legal_rule",
        entity_id=row.id,
        actor_id=author.id,
        meta={"code": row.code, "version": row.version},
    )
    return row


async def update_draft(db: AsyncSession, row: LegalRule, data: dict[str, Any], author: User) -> LegalRule:
    if row.status != RuleStatus.DRAFT:
        raise Conflict("Only drafts can be edited; create a new version", code="rule_not_draft")
    data = dict(data)
    row.meta = {**(row.meta or {}), "autofix": data.pop("autofix", None)}
    check_definition(data)
    for k, v in data.items():
        setattr(row, k, v)
    row.author_id = author.id
    await db.flush()
    return row


async def approve(db: AsyncSession, rule_id: uuid.UUID, approver: User) -> LegalRule:
    row = await db.get(LegalRule, rule_id)
    if row is None:
        raise NotFound("Rule not found")
    if row.status != RuleStatus.DRAFT:
        raise Conflict("Only drafts can be approved", code="rule_not_draft")
    if row.author_id == approver.id:
        raise Forbidden("Author cannot approve their own rule", code="four_eyes")
    check_definition(
        {
            "code": row.code,
            "severity": row.severity.value,
            "message": row.message,
            "scope": row.scope.value,
            "rule_json": row.rule_json,
            "tests": row.tests,
        }
    )
    # Retire previous versions so exactly one version of a code is executable.
    for old in await db.scalars(
        select(LegalRule).where(LegalRule.code == row.code, LegalRule.id != row.id, LegalRule.status.in_(_EXECUTABLE))
    ):
        old.status = RuleStatus.RETIRED
    row.status, row.approved_by, row.approved_at = RuleStatus.APPROVED, approver.id, utcnow()
    await audit.record(
        db,
        action="rule.approve",
        entity="legal_rule",
        entity_id=row.id,
        actor_id=approver.id,
        meta={"code": row.code, "version": row.version},
    )
    return row


async def on_law_changed(db: AsyncSession, lex_doc_id: str, reason: str) -> list[uuid.UUID]:
    rows = list(
        await db.scalars(
            select(LegalRule).where(LegalRule.lex_doc_id == lex_doc_id, LegalRule.status == RuleStatus.APPROVED)
        )
    )
    for r in rows:
        r.status = RuleStatus.NEEDS_REVIEW
        db.add(ContentTask(entity="legal_rule", entity_id=r.id, reason=reason))
    return [r.id for r in rows]
