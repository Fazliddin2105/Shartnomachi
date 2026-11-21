from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import canonical_json, hmac_sha256, random_token, sha256_hex
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.timeutils import ensure_utc, today_local, utcnow
from app.integrations.sms import get_sms_sender
from app.modules.audit import service as audit
from app.modules.auth.otp import normalize_phone
from app.modules.calc.service import bhm_on
from app.modules.contracts import generator
from app.modules.contracts.models import (
    ClauseLibrary,
    Contract,
    ContractParty,
    ContractStatus,
    ContractType,
    ContractVersion,
    FormRequirement,
    PartyRole,
)
from app.modules.files import service as files
from app.modules.notifications.channels import Message, notify
from app.modules.obligations import service as obligations
from app.modules.obligations.models import ObligationKind, ObligationSource
from app.modules.rules import engine
from app.modules.rules import service as rules
from app.modules.users.models import CompanyMember, User

EDITABLE = (ContractStatus.DRAFT, ContractStatus.PENDING_APPROVAL)
SIGNING_ROLES = (PartyRole.A, PartyRole.B)

FORM_WARNING = (
    "Diqqat: ushbu shartnoma qonunga ko'ra {form} shaklni talab qiladi. Platformadagi elektron tasdiq "
    "notarial tasdiq yoki davlat ro'yxatidan o'tkazishni almashtirmaydi."
)
_FORM_TITLES = {"notarial": "notarial tasdiqlangan", "registration": "davlat ro'yxatidan o'tkazilgan"}


# --- types ------------------------------------------------------------------------


async def get_type(db: AsyncSession, code: str) -> ContractType:
    t = await db.scalar(select(ContractType).where(ContractType.code == code, ContractType.is_active.is_(True)))
    if t is None:
        raise NotFound("Contract type not found")
    return t


async def library_for(db: AsyncSession, type_id: uuid.UUID | None) -> list[ClauseLibrary]:
    rows = await db.scalars(
        select(ClauseLibrary)
        .where(
            ClauseLibrary.is_active.is_(True),
            or_(ClauseLibrary.contract_type_id.is_(None), ClauseLibrary.contract_type_id == type_id),
        )
        .order_by(ClauseLibrary.category, ClauseLibrary.title)
    )
    return list(rows)


# --- access policy (row-level security) --------------------------------------------


async def load_for(db: AsyncSession, contract_id: uuid.UUID, user: User) -> tuple[Contract, ContractParty | None]:
    """Only the owner, linked parties, or members of the owning company may see a contract."""
    c = await db.get(Contract, contract_id)
    if c is None:
        raise NotFound("Contract not found")
    party = next((p for p in c.parties if p.user_id == user.id), None)
    if c.owner_id == user.id or party is not None:
        return c, party
    if c.company_id and await db.scalar(
        select(CompanyMember.user_id).where(CompanyMember.company_id == c.company_id, CompanyMember.user_id == user.id)
    ):
        return c, None
    raise NotFound("Contract not found")  # do not leak existence


def require_owner(c: Contract, user: User) -> None:
    if c.owner_id != user.id:
        raise Forbidden("Only the contract initiator can do this", code="not_owner")


def require_editor(c: Contract, user: User, party: ContractParty | None) -> None:
    """Initiator or the lawyer attached to the contract may edit/generate."""
    if c.owner_id == user.id or (party is not None and party.role == PartyRole.LAWYER):
        return
    raise Forbidden("Only the initiator or the contract lawyer can edit", code="not_editor")


async def list_for(db: AsyncSession, user: User, tab: str | None, limit: int, offset: int) -> list[Contract]:
    party_sub = select(ContractParty.contract_id).where(ContractParty.user_id == user.id)
    stmt = select(Contract).where(or_(Contract.owner_id == user.id, Contract.id.in_(party_sub)))
    today = today_local()
    match tab:
        case "active":
            stmt = stmt.where(
                Contract.status == ContractStatus.ACTIVE, or_(Contract.ends_on.is_(None), Contract.ends_on >= today)
            )
        case "pending":
            stmt = stmt.where(Contract.status.in_([ContractStatus.DRAFT, ContractStatus.PENDING_APPROVAL]))
        case "expired":
            stmt = stmt.where(
                or_(
                    Contract.status == ContractStatus.EXPIRED,
                    (Contract.status == ContractStatus.ACTIVE) & (Contract.ends_on < today),
                )
            )
        case "completed":
            stmt = stmt.where(Contract.status == ContractStatus.COMPLETED)
        case "disputed":
            stmt = stmt.where(Contract.status == ContractStatus.DISPUTED)
    stmt = stmt.order_by(Contract.updated_at.desc()).limit(limit).offset(offset)
    return list(await db.scalars(stmt))


# --- create & questionnaire ----------------------------------------------------------


async def create(
    db: AsyncSession,
    *,
    user: User,
    type_code: str,
    title: str | None,
    my_role: PartyRole,
    company_id: uuid.UUID | None,
    represents: PartyRole | None,
) -> Contract:
    ctype = await get_type(db, type_code)
    if company_id and not await db.scalar(
        select(CompanyMember.user_id).where(CompanyMember.company_id == company_id, CompanyMember.user_id == user.id)
    ):
        raise Forbidden("You are not a member of this company")
    c = Contract(
        owner_id=user.id,
        company_id=company_id,
        type_id=ctype.id,
        title=title or ctype.title_uz,
        form_requirement=ctype.form_requirement,
        answers={},
    )
    if my_role == PartyRole.LAWYER:
        if represents not in SIGNING_ROLES:
            raise ValidationFailed("Lawyer must represent party A or B", code="represents_required")
        c.parties = [
            ContractParty(role=PartyRole.LAWYER, represents=represents, user_id=user.id, joined_at=utcnow()),
            ContractParty(role=PartyRole.A),
            ContractParty(role=PartyRole.B),
        ]
    elif my_role in SIGNING_ROLES:
        other = PartyRole.B if my_role == PartyRole.A else PartyRole.A
        c.parties = [
            ContractParty(role=my_role, user_id=user.id, company_id=company_id, joined_at=utcnow()),
            ContractParty(role=other),
        ]
    else:
        raise ValidationFailed("Initiator must be party A, B or a lawyer", code="role_invalid")
    db.add(c)
    await db.flush()
    await log_event(
        db,
        c,
        actor_id=user.id,
        side=represents.value if my_role == PartyRole.LAWYER and represents else my_role.value,
        kind="created",
    )
    await audit.record(
        db,
        action="contract.create",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"type": type_code, "role": my_role.value},
    )
    return c


def _fields(questionnaire: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for s in questionnaire.get("sections", []) for f in s.get("fields", [])]


def _required_if(f: dict[str, Any], answers: dict[str, Any]) -> bool:
    """`"required_if": {"field": "b_via_representative", "in": ["yes"]}` — conditionally mandatory field."""
    cond = f.get("required_if")
    if not cond:
        return False
    v = engine.get_path(answers, cond["field"])
    return v is not engine._MISSING and v in cond.get("in", [])


def check_answers(questionnaire: dict[str, Any], answers: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """Returns (missing required fields, type errors)."""
    missing: list[str] = []
    errors: list[dict[str, str]] = []
    for f in _fields(questionnaire):
        key, ftype = f["key"], f.get("type", "string")
        v = engine.get_path(answers, key)
        if v is engine._MISSING or v in (None, "", []):
            if f.get("required") or _required_if(f, answers):
                missing.append(key)
            continue
        if ftype == "party":
            if not isinstance(v, dict) or not v.get("name"):
                (missing if f.get("required") else []).append(f"{key}.name")
            continue
        try:
            if ftype == "number":
                n = Decimal(str(v))
                if "min" in f and n < Decimal(str(f["min"])):
                    errors.append({"field": key, "error": f"must be >= {f['min']}"})
                if "max" in f and n > Decimal(str(f["max"])):
                    errors.append({"field": key, "error": f"must be <= {f['max']}"})
            elif ftype == "date":
                date.fromisoformat(str(v))
            elif ftype == "boolean" and not isinstance(v, bool):
                errors.append({"field": key, "error": "must be boolean"})
            elif ftype == "enum" and v not in [o["value"] if isinstance(o, dict) else o for o in f.get("options", [])]:
                errors.append({"field": key, "error": "unknown option"})
            elif ftype in ("string", "text") and f.get("pattern") and not re.fullmatch(f["pattern"], str(v).strip()):
                errors.append({"field": key, "error": f"format: {f.get('hint') or f['pattern']}"})
        except (InvalidOperation, ValueError):
            errors.append({"field": key, "error": f"must be a valid {ftype}"})
    return missing, errors


def _apply_meta_fields(c: Contract, ctype: ContractType) -> None:
    meta = (ctype.questionnaire or {}).get("meta_fields", {})
    a = c.answers or {}

    def pick(name: str) -> Any:
        key = meta.get(name)
        return a.get(key) if key else None

    try:
        amount = pick("amount")
        c.total_amount = Decimal(str(amount)) if amount not in (None, "") else None
    except InvalidOperation:
        c.total_amount = None
    for attr in ("starts_on", "ends_on"):
        v = pick(attr)
        try:
            setattr(c, attr, date.fromisoformat(str(v)) if v else None)
        except ValueError:
            setattr(c, attr, None)
    c.currency = str(a.get(meta.get("currency", ""), "UZS") or "UZS")[:3]


def expand_dotted(answers: dict[str, Any]) -> dict[str, Any]:
    """{"party_a.name": "X"} -> {"party_a": {"name": "X"}} (questionnaire keys are dotted paths)."""
    out: dict[str, Any] = {}
    for key, value in answers.items():
        if isinstance(value, dict):
            value = expand_dotted(value)
        parts = str(key).split(".")
        cur = out
        for p in parts[:-1]:
            nxt = cur.get(p)
            if not isinstance(nxt, dict):
                nxt = cur[p] = {}
            cur = nxt
        last = parts[-1]
        if isinstance(value, dict) and isinstance(cur.get(last), dict):
            cur[last] = deep_merge(cur[last], value)
        else:
            cur[last] = value
    return out


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Nested dicts are merged key by key, so saving one field of a party keeps the others."""
    out = dict(base)
    for k, v in patch.items():
        if v is None or v == "":
            out.pop(k, None)  # «tozalash»: an emptied field disappears from the answers
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
            if not out[k]:
                out.pop(k)
        else:
            out[k] = v
    return out


async def patch_answers(
    db: AsyncSession,
    c: Contract,
    user: User,
    *,
    answers: dict[str, Any],
    merge: bool,
    selected_clauses: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if c.status not in EDITABLE:
        raise Conflict("Contract can no longer be edited", code="contract_locked")
    answers = expand_dotted(answers)
    c.answers = deep_merge(c.answers or {}, answers) if merge else answers
    if selected_clauses is not None:
        lib_ids = {uuid.UUID(str(s["clause_id"])) for s in selected_clauses}
        found = {x.id for x in await library_for(db, c.type_id) if x.id in lib_ids}
        if lib_ids - found:
            raise ValidationFailed("Unknown library clause", code="clause_unknown")
        c.selected_clauses = [
            {"clause_id": str(s["clause_id"]), "params": s.get("params", {})} for s in selected_clauses
        ]
    if c.status == ContractStatus.PENDING_APPROVAL:
        # Any change invalidates collected approvals: a new version must be generated.
        c.status = ContractStatus.DRAFT
        for p in c.parties:
            p.confirmed_at = None
    assert c.contract_type is not None
    _apply_meta_fields(c, c.contract_type)
    result = await validate(db, c)
    await db.flush()
    return result


async def autofix(db: AsyncSession, c: Contract, user: User) -> dict[str, Any]:
    """Apply every rule's machine fix (`autofix: {field, value}`) and re-validate."""
    report = await validate(db, c)
    fixes: dict[str, Any] = {}
    for f in report["findings"]:
        af = f.get("autofix") or {}
        field = str(af.get("field") or "")
        if field.startswith("answers.") and "value" in af:
            fixes[field.removeprefix("answers.")] = af["value"]
    if not fixes:
        return {"applied": [], **report}
    result = await patch_answers(db, c, user, answers=fixes, merge=True, selected_clauses=None)
    await audit.record(
        db,
        action="contract.autofix",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"fields": sorted(fixes)},
    )
    return {"applied": [{"field": k, "value": v} for k, v in fixes.items()], **result}


# --- validation ------------------------------------------------------------------------


async def _context(db: AsyncSession, c: Contract) -> dict[str, Any]:
    try:
        bhm = float(await bhm_on(db, today_local()))
    except NotFound:
        bhm = None
    amount = float(c.total_amount) if c.total_amount is not None else None
    duration_days = (c.ends_on - c.starts_on).days if c.starts_on and c.ends_on else None
    return {
        "answers": c.answers or {},
        "contract": {
            "type": c.contract_type.code if c.contract_type else None,
            "amount": amount,
            "currency": c.currency,
            "duration_days": duration_days,
            "duration_months": round(duration_days / 30.44, 2) if duration_days is not None else None,
        },
        "derived": {"bhm": bhm, "amount_in_bhm": round(amount / bhm, 2) if amount is not None and bhm else None},
    }


def _form_requirement(ctype: ContractType, ctx: dict[str, Any]) -> tuple[FormRequirement, list[str]]:
    form, reasons = ctype.form_requirement, []
    for fr in ctype.form_rules or []:
        if engine.evaluate(fr["when"], ctx):
            candidate = FormRequirement(fr["form"])
            reasons.append(fr.get("reason", ""))
            if candidate.rank > form.rank:
                form = candidate
    return form, reasons


async def _extra_clauses(db: AsyncSession, c: Contract) -> list[dict[str, Any]]:
    if not c.selected_clauses:
        return []
    lib = {str(x.id): x for x in await library_for(db, c.type_id)}
    out = []
    for s in c.selected_clauses:
        item = lib.get(s["clause_id"])
        if item:
            out.append(
                {
                    "body_template": item.body_template,
                    "params": s.get("params", {}),
                    "category": item.category,
                    "code": item.code,
                }
            )
    return out


def party_names(c: Contract) -> dict[str, str | None]:
    a = c.answers or {}
    return {side: (a.get(f"party_{side.lower()}") or {}).get("name") for side in ("A", "B")}


async def preview(db: AsyncSession, c: Contract, *, language: str) -> dict[str, Any]:
    ctype = c.contract_type
    if ctype is None:
        raise ValidationFailed("Contract has no type", code="type_missing")
    template = ctype.template if language == "uz" else ctype.template_ru
    if not template:
        raise ValidationFailed(f"Template for language '{language}' is not available", code="language_unavailable")
    return generator.render_content(
        template=template,
        answers=c.answers or {},
        extra_clauses=await _extra_clauses(db, c),
        type_code=ctype.code,
        language=language,
        form_requirement=c.form_requirement.value,
    )


async def validate(db: AsyncSession, c: Contract) -> dict[str, Any]:
    ctype = c.contract_type
    if ctype is None:
        raise ValidationFailed("Contract has no type", code="type_missing")
    ctx = await _context(db, c)
    active = await rules.active_rules(db, ctype.id)
    findings = engine.run_answers(active, ctx)

    # Clause-level rules also run on the rendered text (incl. library/custom clauses).
    content = generator.render_content(
        template=ctype.template,
        answers=c.answers or {},
        extra_clauses=await _extra_clauses(db, c),
        type_code=ctype.code,
        language=c.language,
        form_requirement=c.form_requirement.value,
    )
    clauses = [
        {"index": i, "text": s["text"], "category": s.get("category"), "title": s["title"]}
        for i, s in enumerate(content["sections"])
    ]
    findings = engine.sort_findings(findings + engine.run_clauses(active, clauses, ctx))

    missing, type_errors = check_answers(ctype.questionnaire, c.answers or {})
    form, reasons = _form_requirement(ctype, ctx)
    c.form_requirement = form
    summary = engine.summarize(findings)
    field_warnings: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        for path in f.fields or []:
            if str(path).startswith("answers."):
                field_warnings.setdefault(str(path).removeprefix("answers."), []).append(
                    {
                        "severity": f.severity.value,
                        "rule_code": f.rule_code,
                        "message": f.message,
                        "fix_suggestion": f.fix_suggestion,
                        "law_ref": f.law_ref,
                        "lex_url": f.lex_url,
                    }
                )
    result = {
        "findings": [f.to_dict() for f in findings],
        "summary": summary,
        "field_warnings": field_warnings,
        "missing_fields": missing,
        "field_errors": type_errors,
        "form": {
            "requirement": form.value,
            "reasons": [r for r in reasons if r],
            "warning": FORM_WARNING.format(form=_FORM_TITLES[form.value]) if form != FormRequirement.SIMPLE else None,
        },
        "ready": not missing and not type_errors,
        "disclaimer": "Platforma huquqiy axborot beradi va malakali yurist maslahatini almashtirmaydi.",
    }
    c.validation = {"summary": summary, "missing": len(missing), "form": form.value, "at": utcnow().isoformat()}
    return result


# --- generation ----------------------------------------------------------------------


async def generate(
    db: AsyncSession, c: Contract, user: User, *, language: str
) -> tuple[ContractVersion, dict[str, Any]]:
    if c.status not in EDITABLE:
        raise Conflict("Contract can no longer be regenerated", code="contract_locked")
    ctype = c.contract_type
    assert ctype is not None
    report = await validate(db, c)
    if not report["ready"]:
        raise ValidationFailed(
            "Questionnaire is incomplete",
            code="answers_incomplete",
            details={"missing": report["missing_fields"], "errors": report["field_errors"]},
        )
    if report["summary"]["blocking"]:
        # Policy: a contract with clauses contrary to law is never produced by the platform.
        raise ValidationFailed(
            "Contract contains clauses contrary to law",
            code="illegal_clauses",
            details=[f for f in report["findings"] if f["severity"] == "red"],
        )
    template = ctype.template if language == "uz" else ctype.template_ru
    if not template:
        raise ValidationFailed(f"Template for language '{language}' is not available", code="language_unavailable")

    content = generator.render_content(
        template=template,
        answers=c.answers or {},
        extra_clauses=await _extra_clauses(db, c),
        type_code=ctype.code,
        language=language,
        form_requirement=c.form_requirement.value,
    )
    content["contract_id"] = str(c.id)
    digest = sha256_hex(canonical_json(content))
    last = await db.scalar(
        select(ContractVersion.number)
        .where(ContractVersion.contract_id == c.id)
        .order_by(ContractVersion.number.desc())
        .limit(1)
    )
    number = (last or 0) + 1
    docx = generator.build_docx(content, version=number, sha256=digest)
    stored = await files.save_bytes(
        db,
        data=docx,
        filename=f"shartnoma-v{number}.docx",
        declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        owner_id=user.id,
        purpose="contract",
        trusted_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    v = ContractVersion(
        contract_id=c.id,
        number=number,
        content=content,
        sha256=digest,
        file_id=stored.id,
        validation=report["summary"],
        red_acknowledged=False,
        created_by=user.id,
    )
    db.add(v)
    await db.flush()
    c.current_version_id, c.language, c.status = v.id, language, ContractStatus.PENDING_APPROVAL
    for p in c.parties:
        p.confirmed_at = None
    await audit.record(
        db,
        action="contract.generate",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"version": number, "sha256": digest, "red_acknowledged": v.red_acknowledged},
    )
    return v, report


async def current_version(db: AsyncSession, c: Contract) -> ContractVersion:
    if c.current_version_id is None:
        raise ValidationFailed("Contract has not been generated yet", code="no_version")
    v = await db.get(ContractVersion, c.current_version_id)
    assert v is not None
    return v


async def version_pdf(db: AsyncSession, v: ContractVersion, user: User) -> uuid.UUID:
    if v.pdf_file_id:
        return v.pdf_file_id
    assert v.file_id is not None
    docx = await files.read_bytes(await files.get_file(db, v.file_id))
    pdf = await generator.docx_to_pdf(docx)
    stored = await files.save_bytes(
        db,
        data=pdf,
        filename=f"shartnoma-v{v.number}.pdf",
        declared_mime="application/pdf",
        owner_id=user.id,
        purpose="contract",
    )
    v.pdf_file_id = stored.id
    return stored.id


def verify_integrity(v: ContractVersion) -> dict[str, Any]:
    recomputed = sha256_hex(canonical_json(v.content))
    return {
        "version": v.number,
        "stored_sha256": v.sha256,
        "recomputed_sha256": recomputed,
        "intact": recomputed == v.sha256,
    }


# --- parties / invitations --------------------------------------------------------------


def _invite_hash(token: str) -> str:
    return hmac_sha256(token, purpose="invite")


def phone_hash(phone: str) -> str:
    return hmac_sha256(phone, purpose="invite_phone")


INVITE_TTL = timedelta(days=14)
_ROLE_TITLES = {
    PartyRole.A: "A tomon",
    PartyRole.B: "B tomon",
    PartyRole.LAWYER: "yurist",
    PartyRole.OBSERVER: "kuzatuvchi",
}


def role_title(role: PartyRole) -> str:
    return _ROLE_TITLES.get(role, role.value)


async def _notify(db: AsyncSession, user_id: uuid.UUID | None, msg: Message, channels: list[str] | None = None) -> None:
    if user_id is None:
        return
    target = await db.get(User, user_id)
    if target is not None:
        await notify(db, target, msg, channels)


async def log_event(
    db: AsyncSession,
    c: Contract,
    *,
    actor_id: uuid.UUID | None,
    side: str | None,
    kind: str,
    payload: dict[str, Any] | None = None,
    merge_window_s: int | None = None,
) -> None:
    """Append a negotiation timeline entry; with `merge_window_s`, a burst of the same actor's edits
    (autosave on every keystroke) is folded into one entry instead of flooding the timeline."""
    from app.modules.contracts.models import ContractEvent

    if merge_window_s:
        last = await db.scalar(
            select(ContractEvent)
            .where(ContractEvent.contract_id == c.id, ContractEvent.kind == kind, ContractEvent.actor_id == actor_id)
            .order_by(ContractEvent.created_at.desc())
            .limit(1)
        )
        if last is not None and utcnow() - ensure_utc(last.created_at) < timedelta(seconds=merge_window_s):
            old = dict(last.payload or {})
            fields = sorted(set(old.get("fields", [])) | set((payload or {}).get("fields", [])))
            last.payload = {**old, **(payload or {}), "fields": fields[:100]}
            last.created_at = utcnow()
            return
    db.add(ContractEvent(contract_id=c.id, actor_id=actor_id, side=side, kind=kind, payload=payload or {}))
    await db.flush()


async def notify_parties(
    db: AsyncSession, c: Contract, *, except_user: uuid.UUID | None, title: str, body: str, event: str
) -> None:
    """Tell the owner and every joined party about a contract event (in-app + their channels)."""
    seen: set[uuid.UUID] = set()
    for uid in [c.owner_id, *(p.user_id for p in c.parties)]:
        if uid is None or uid == except_user or uid in seen:
            continue
        seen.add(uid)
        await _notify(db, uid, Message(type=event, title=title, body=body, payload={"contract_id": str(c.id)}))


async def invite(
    db: AsyncSession,
    c: Contract,
    user: User,
    *,
    phone: str,
    role: PartyRole,
    represents: PartyRole | None,
    display_name: str | None,
) -> tuple[ContractParty, str]:
    require_owner(c, user)
    if c.status not in EDITABLE:
        raise Conflict("Contract is locked", code="contract_locked")
    phone = normalize_phone(phone)
    if role in SIGNING_ROLES:
        party = next((p for p in c.parties if p.role == role), None)
        if party is None:
            party = ContractParty(role=role)
            c.parties.append(party)
        if party.user_id is not None:
            raise Conflict(f"Party {role.value} already joined", code="party_taken")
    else:
        party = ContractParty(role=role, represents=represents)
        c.parties.append(party)
    token = random_token(24)
    party.invite_phone, party.invite_token_hash, party.invited_at = phone, _invite_hash(token), utcnow()
    party.invite_phone_hash = phone_hash(phone)
    party.display_name = display_name
    await db.flush()
    await log_event(db, c, actor_id=user.id, side=None, kind="invited", payload={"role": role.value})
    await get_sms_sender().send(
        phone, f'LexLab: sizni "{c.title[:40]}" shartnomasiga taklif qilishdi. Taklif kodi: {token}'
    )
    # Already registered invitee: also show it in the app (SMS stays the primary channel).
    invitee = await db.scalar(select(User.id).where(User.phone == phone))
    if invitee is not None and invitee != user.id:
        await _notify(
            db,
            invitee,
            Message(
                type="contract.invited",
                title="Sizni shartnomaga taklif qilishdi",
                body=f"\"{c.title}\" — {role_title(role)} sifatida. Takliflar ro'yxatida ko'ring.",
                payload={"contract_id": str(c.id), "party_id": str(party.id)},
            ),
            channels=["in_app"],
        )
    await audit.record(
        db,
        action="contract.invite",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"role": role.value, "party_id": str(party.id)},
    )
    return party, token


async def accept_invite(db: AsyncSession, user: User, token: str) -> Contract:
    party = await db.scalar(select(ContractParty).where(ContractParty.invite_token_hash == _invite_hash(token)))
    if party is None:
        raise NotFound("Invitation not found or already used", code="invite_invalid")
    return await _join(db, user, party)


def _invite_expired(party: ContractParty) -> bool:
    return bool(party.invited_at and utcnow() - ensure_utc(party.invited_at) > INVITE_TTL)


async def list_invitations(db: AsyncSession, user: User) -> list[tuple[ContractParty, Contract]]:
    """Open invitations addressed to the caller's (OTP-verified) phone number."""
    if not user.phone:
        return []
    rows = await db.execute(
        select(ContractParty, Contract)
        .join(Contract, Contract.id == ContractParty.contract_id)
        .where(
            ContractParty.invite_phone_hash == phone_hash(user.phone),
            ContractParty.user_id.is_(None),
            ContractParty.invite_token_hash.is_not(None),
            Contract.status.in_(EDITABLE),
        )
        .order_by(ContractParty.invited_at.desc())
    )
    # Decrypted phone is re-checked: the blind index alone is never trusted for authorization.
    return [(p, c) for p, c in rows.tuples() if not _invite_expired(p) and p.invite_phone == user.phone]


async def _open_invitation(db: AsyncSession, user: User, party_id: uuid.UUID) -> ContractParty:
    party = await db.get(ContractParty, party_id)
    if party is None or party.invite_token_hash is None or party.user_id is not None:
        raise NotFound("Invitation not found or already used", code="invite_invalid")
    if not user.phone or party.invite_phone != user.phone:
        raise Forbidden("This invitation was sent to another phone number", code="invite_phone_mismatch")
    return party


async def accept_invitation(db: AsyncSession, user: User, party_id: uuid.UUID) -> Contract:
    """Accept without the SMS token: phone ownership is already proven by the OTP login."""
    return await _join(db, user, await _open_invitation(db, user, party_id))


async def decline_invitation(db: AsyncSession, user: User, party_id: uuid.UUID) -> None:
    party = await _open_invitation(db, user, party_id)
    c = await db.get(Contract, party.contract_id)
    assert c is not None
    party.invite_token_hash = None
    party.invite_phone_hash = None
    await audit.record(
        db,
        action="contract.invite_declined",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"role": party.role.value, "party_id": str(party.id)},
    )
    await _notify(
        db,
        c.owner_id,
        Message(
            type="contract.invite_declined",
            title="Taklif rad etildi",
            body=f'"{c.title}": {role_title(party.role)} taklifni rad etdi.',
            payload={"contract_id": str(c.id)},
        ),
    )


async def _join(db: AsyncSession, user: User, party: ContractParty) -> Contract:
    if _invite_expired(party):
        raise ValidationFailed("Invitation expired", code="invite_expired")
    if party.invite_phone and user.phone != party.invite_phone:
        raise Forbidden("This invitation was sent to another phone number", code="invite_phone_mismatch")
    c = await db.get(Contract, party.contract_id)
    assert c is not None
    if c.status not in EDITABLE:
        raise Conflict("Contract is no longer open for joining", code="contract_locked")
    if (
        any(p.user_id == user.id and p.id != party.id and p.role in SIGNING_ROLES for p in c.parties)
        and party.role in SIGNING_ROLES
    ):
        raise Conflict("You are already a signing party of this contract", code="already_party")
    party.user_id, party.joined_at, party.invite_token_hash = user.id, utcnow(), None
    party.invite_phone_hash = None
    await log_event(
        db,
        c,
        actor_id=user.id,
        side=party.represents.value if party.represents else party.role.value,
        kind="joined",
        payload={"role": party.role.value},
    )
    await audit.record(
        db, action="contract.join", entity="contract", entity_id=c.id, actor_id=user.id, meta={"role": party.role.value}
    )
    await notify_parties(
        db,
        c,
        except_user=user.id,
        event="contract.joined",
        title="Ikkinchi tomon qo'shildi",
        body=f'"{c.title}": {role_title(party.role)} qo\'shildi. Endi shartnomani tasdiqlash mumkin.',
    )
    return c


# --- lifecycle ---------------------------------------------------------------------------


async def activate(db: AsyncSession, c: Contract) -> None:
    """All signing parties approved => contract becomes active; obligations are derived."""
    c.status, c.activated_at = ContractStatus.ACTIVE, utcnow()
    ctype = c.contract_type
    if ctype is None:
        return
    by_role = {p.role: p for p in c.parties}
    for tpl in ctype.obligation_templates or []:
        party = by_role.get(PartyRole(tpl["party"]))
        if party is None or party.user_id is None:
            continue
        for spec in derive_obligations(tpl, c.answers or {}):
            await obligations.create(
                db,
                owner_id=party.user_id,
                contract_id=c.id,
                party_id=party.id,
                source=ObligationSource.CONTRACT,
                kind=ObligationKind(tpl.get("kind", "duty")),
                title=tpl["title"],
                currency=c.currency,
                **spec,
            )
    await audit.record(db, action="contract.activate", entity="contract", entity_id=c.id, actor_id=None)


def derive_obligations(tpl: dict[str, Any], answers: dict[str, Any]) -> list[dict[str, Any]]:
    """Turns an obligation template + answers into `obligations.create` kwargs."""
    due = tpl.get("due", {})

    def d(field: str | None) -> date | None:
        v = answers.get(field) if field else None
        try:
            return date.fromisoformat(str(v)) if v else None
        except ValueError:
            return None

    amount = None
    if tpl.get("amount_field") and answers.get(tpl["amount_field"]) not in (None, ""):
        try:
            amount = Decimal(str(answers[tpl["amount_field"]]))
        except InvalidOperation:
            amount = None
    base: dict[str, Any] = {
        "amount": amount,
        "description": tpl.get("description"),
        "source_clause_ref": tpl.get("clause_ref"),
    }
    match due.get("type"):
        case "date":
            when = d(due.get("field"))
            return [{**base, "due_date": when}] if when else []
        case "offset_days":
            start = d(due.get("start_field"))
            raw_days = answers.get(due["days_field"]) if due.get("days_field") else None
            try:
                days = int(Decimal(str(raw_days))) if raw_days not in (None, "") else int(due.get("days", 0))
            except InvalidOperation:
                days = int(due.get("days", 0))
            return [{**base, "due_date": start + timedelta(days=days)}] if start else []
        case "recurring_monthly":
            start = d(due.get("start_field"))
            day = int(answers.get(due.get("day_field", ""), 0) or due.get("day", 1))
            day = min(max(day, 1), 28)
            if not start:
                return []
            first = start.replace(day=day)
            if first < start:
                first = (first.replace(day=1) + timedelta(days=32)).replace(day=day)
            return [
                {
                    **base,
                    "due_date": first,
                    "recurrence_rule": f"FREQ=MONTHLY;BYMONTHDAY={day}",
                    "recurrence_until": d(due.get("until_field")),
                }
            ]
    return []


async def set_status(db: AsyncSession, c: Contract, user: User, new: ContractStatus, reason: str | None) -> Contract:
    allowed: dict[ContractStatus, set[ContractStatus]] = {
        ContractStatus.ACTIVE: {ContractStatus.COMPLETED, ContractStatus.DISPUTED},
        ContractStatus.DISPUTED: {ContractStatus.ACTIVE, ContractStatus.COMPLETED},
        ContractStatus.EXPIRED: {ContractStatus.COMPLETED, ContractStatus.DISPUTED},
        ContractStatus.DRAFT: {ContractStatus.CANCELLED},
        ContractStatus.PENDING_APPROVAL: {ContractStatus.CANCELLED},
    }
    if new not in allowed.get(c.status, set()):
        raise Conflict(f"Cannot change status from {c.status.value} to {new.value}", code="status_transition")
    if new == ContractStatus.CANCELLED:
        require_owner(c, user)
    old = c.status
    c.status = new
    await audit.record(
        db,
        action="contract.status",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"from": old.value, "to": new.value, "reason": reason},
    )
    return c


# --- AI (advisory layer; the rule engine stays authoritative) ----------------------------------


async def _clauses_for_ai(db: AsyncSession, c: Contract) -> list[dict[str, Any]]:
    if c.current_version_id and c.status != ContractStatus.DRAFT:
        content = (await current_version(db, c)).content
    else:
        content = await preview(db, c, language="uz")
    return [{"index": i, "text": f"{s_['title']}\n{s_['text']}".strip()} for i, s_ in enumerate(content["sections"])]


def laws_for_type(ctype: ContractType | None) -> list[str] | None:
    """Article texts (lex.uz) relevant to the contract type, for the AI prompt."""
    from app.modules.laws import corpus

    if ctype is None:
        return None
    return corpus.prompt_block(corpus.articles_for(ctype.legal_refs)) or None


async def ai_review(db: AsyncSession, c: Contract) -> dict[str, Any]:
    from app.ai import service as ai

    clauses = await _clauses_for_ai(db, c)
    report = await validate(db, c)
    rule_findings = [{"clause_index": f.get("clause_index"), "message": f["message"]} for f in report["findings"]]
    from app.modules.contracts.reference import reference_for

    ctype = c.contract_type
    ref = reference_for(ctype)
    result = await ai.review(
        clauses=clauses,
        contract_type=ctype.title_uz if ctype else None,
        rule_findings=rule_findings,
        template_clauses=ref.texts if ref else None,
        template_label=ref.label if ref else None,
        law_texts=laws_for_type(ctype),
    )
    out = result.to_dict()
    out["rule_findings"] = len(rule_findings)
    out["disclaimer"] = "AI tavsiyalari ma'lumot uchun; yakuniy qonuniylik xulosasini qoidalar tizimi va yurist beradi."
    return out


async def ai_ask(db: AsyncSession, c: Contract, question: str) -> dict[str, Any]:
    from app.ai import service as ai

    clauses = await _clauses_for_ai(db, c)
    report = await validate(db, c)
    ctype = c.contract_type
    return await ai.ask(
        clauses=clauses,
        findings=[f["message"] for f in report["findings"]],
        question=question,
        contract_type=ctype.title_uz if ctype else None,
        law_texts=law_context(ctype, question),
    )


def law_context(ctype: ContractType | None, question: str | None = None) -> list[str] | None:
    """Articles of the contract type plus those most relevant to the user's question (lex.uz text)."""
    from app.modules.laws import corpus

    arts = corpus.articles_for(ctype.legal_refs, max_chars=700) if ctype else []
    if question:
        codes = sorted({r["code"] for r in (ctype.legal_refs or []) if r.get("code")}) if ctype else []
        seen = {(a["code"], str(a["number"])) for a in arts}
        for a in corpus.related(question, codes=codes or None, limit=4):
            if (a["code"], str(a["number"])) not in seen:
                arts.append(a)
    return corpus.prompt_block(arts) or None
