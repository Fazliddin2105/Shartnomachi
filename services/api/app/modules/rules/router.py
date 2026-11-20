from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, PageParams, require
from app.core.errors import NotFound
from app.core.rbac import Perm
from app.modules.rules import engine, service
from app.modules.rules.engine import Scope, Severity
from app.modules.rules.models import LegalRule, RuleStatus
from app.modules.users.models import User

router = APIRouter(prefix="/cms/rules", tags=["cms"])
Author = Annotated[User, Depends(require(Perm.RULES_WRITE))]
Approver = Annotated[User, Depends(require(Perm.RULES_APPROVE))]


class RuleIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    contract_type_id: uuid.UUID | None = None
    scope: Scope = Scope.ANSWERS
    category: str | None = None
    severity: Severity
    rule_json: dict[str, Any] = Field(description="`when` sharti")
    message: str
    fix_suggestion: str | None = None
    law_ref: str | None = None
    lex_url: str | None = None
    lex_doc_id: str | None = None
    tests: list[dict[str, Any]] = Field(default_factory=list)
    autofix: dict[str, Any] | None = Field(default=None, description='{"field": "answers.x", "value": 3}')


class RuleOut(RuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    status: RuleStatus
    approved_at: datetime | None


class RuleTryIn(BaseModel):
    rule: RuleIn
    context: dict[str, Any]


class LawChangeIn(BaseModel):
    lex_doc_id: str
    reason: str = "Lex.uz: hujjatga o'zgartirish kiritildi"


@router.get("", response_model=list[RuleOut])
async def list_rules(
    db: DB, _: Author, page: PageParams, status_: RuleStatus | None = None, code: str | None = None
) -> list[RuleOut]:
    stmt = select(LegalRule).order_by(LegalRule.code, LegalRule.version.desc())
    if status_:
        stmt = stmt.where(LegalRule.status == status_)
    if code:
        stmt = stmt.where(LegalRule.code == code)
    return [RuleOut.model_validate(r) for r in await db.scalars(stmt.limit(page.limit).offset(page.offset))]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED, summary="Yangi qoida / yangi versiya")
async def create_rule(body: RuleIn, db: DB, user: Author) -> RuleOut:
    return RuleOut.model_validate(await service.create_draft(db, body.model_dump(), user))


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: uuid.UUID, body: RuleIn, db: DB, user: Author) -> RuleOut:
    row = await db.get(LegalRule, rule_id)
    if row is None:
        raise NotFound("Rule not found")
    return RuleOut.model_validate(await service.update_draft(db, row, body.model_dump(), user))


@router.post("/{rule_id}/approve", response_model=RuleOut, summary="Huquqiy ekspert tasdig'i (4 ko'z)")
async def approve_rule(rule_id: uuid.UUID, db: DB, user: Approver) -> RuleOut:
    return RuleOut.model_validate(await service.approve(db, rule_id, user))


@router.post("/try", summary="Qoidani saqlamasdan sinash (test to'plami)")
async def try_rule(body: RuleTryIn, _: Author) -> dict[str, Any]:
    rule = service.check_definition({**body.rule.model_dump(), "tests": []})
    if rule.scope == Scope.CLAUSE:
        findings = engine.run_clauses([rule], [body.context.get("clause", {})], body.context)
    else:
        findings = engine.run_answers([rule], body.context)
    return {
        "triggered": bool(findings),
        "findings": [f.to_dict() for f in findings],
        "tests": engine.run_tests(rule, body.rule.tests),
    }


@router.post("/law-changed", summary="Lex.uz o'zgarishi: bog'liq qoidalarni «tekshirilsin» holatiga o'tkazish")
async def law_changed(body: LawChangeIn, db: DB, _: Author) -> dict[str, Any]:
    rules = await service.on_law_changed(db, body.lex_doc_id, body.reason)
    return {"rules_flagged": [str(r) for r in rules]}
