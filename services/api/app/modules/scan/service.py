from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import llm
from app.ai import service as ai
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.timeutils import utcnow
from app.db.session import session_scope
from app.modules.audit import service as audit
from app.modules.contracts import service as contracts_service
from app.modules.contracts.models import ContractType
from app.modules.contracts.reference import reference_for
from app.modules.files import service as files
from app.modules.notifications import channels
from app.modules.obligations import service as obligations
from app.modules.obligations.models import ObligationKind, ObligationSource
from app.modules.rules import engine
from app.modules.rules import service as rules
from app.modules.scan import analysis, extract
from app.modules.scan.models import Decision, FindingKind, ScanFinding, ScanJob, ScanStatus
from app.modules.users.models import User
from app.workers import queue

log = logging.getLogger(__name__)

OCR_REVIEW_THRESHOLD = 80.0


async def create_job(
    db: AsyncSession,
    *,
    user: User,
    data: bytes,
    filename: str,
    mime: str | None,
    contract_type_code: str | None,
    side: str | None,
) -> ScanJob:
    stored = await files.save_bytes(
        db, data=data, filename=filename, declared_mime=mime, owner_id=user.id, purpose="scan"
    )
    job = ScanJob(owner_id=user.id, file_id=stored.id, contract_type_code=contract_type_code, side=side)
    db.add(job)
    await db.flush()
    await audit.record(
        db,
        action="scan.create",
        entity="scan_job",
        entity_id=job.id,
        actor_id=user.id,
        meta={"file_sha256": stored.sha256},
    )
    return job


async def get_owned(db: AsyncSession, job_id: uuid.UUID, user: User) -> ScanJob:
    job = await db.get(ScanJob, job_id)
    if job is None or job.owner_id != user.id:
        raise NotFound("Scan not found")
    return job


async def process(job_id: uuid.UUID) -> None:
    """Background entry point (worker / in-process task). Owns its transaction."""
    await _process(job_id)
    await queue_ai_review(job_id)


async def queue_ai_review(job_id: uuid.UUID) -> None:
    """Called after the analysis is committed, so the AI job sees the stored text and findings."""
    if not llm.is_enabled():
        return
    async with session_scope() as db:
        job = await db.get(ScanJob, job_id)
        if job is None or job.status != ScanStatus.DONE:
            return
        job.ai_status = "pending"
    await queue.enqueue("ai_review_scan", job_id)


async def _process(job_id: uuid.UUID) -> None:
    async with session_scope() as db:
        job = await db.get(ScanJob, job_id)
        if job is None or job.status not in (ScanStatus.QUEUED, ScanStatus.FAILED):
            return
        job.status = ScanStatus.PROCESSING
        await db.flush()
        try:
            stored = await files.get_file(db, job.file_id) if job.file_id else None
            if stored is None:
                raise ValidationFailed("File missing", code="file_missing")
            ex = await extract.extract_text(await files.read_bytes(stored), stored.mime)
            job.extraction, job.ocr_confidence = ex.method, ex.confidence
            job.ocr_text = analysis.clean_text(ex.text)
            if not job.ocr_text or len(job.ocr_text) < 50:
                raise ValidationFailed("Could not read text from the document", code="no_text")
            if ex.method == "ocr" and (ex.confidence or 0) < OCR_REVIEW_THRESHOLD:
                # Spec §5.4: user must confirm/correct OCR output before we judge it.
                job.status = ScanStatus.NEEDS_REVIEW
                return
            job.text_confirmed = ex.method != "ocr"
            await analyze(db, job)
        except AppError as e:
            job.status, job.error = ScanStatus.FAILED, f"{e.code}: {e.message}"[:500]
        except Exception as e:
            log.exception("scan_failed", extra={"job_id": str(job_id)})
            job.status, job.error = ScanStatus.FAILED, f"internal: {type(e).__name__}"


async def confirm_text(db: AsyncSession, job: ScanJob, text: str) -> ScanJob:
    if job.status not in (ScanStatus.NEEDS_REVIEW, ScanStatus.DONE):
        raise Conflict("Scan is not ready for text review", code="scan_not_reviewable")
    job.ocr_text, job.text_confirmed = analysis.clean_text(text), True
    await analyze(db, job)
    return job


async def analyze(db: AsyncSession, job: ScanJob) -> None:
    text = job.ocr_text or ""
    types = list(await db.scalars(select(ContractType).where(ContractType.is_active.is_(True))))
    ctype: ContractType | None = None
    if job.contract_type_code:
        ctype = next((t for t in types if t.code == job.contract_type_code), None)
    if ctype is None:
        code = analysis.detect_type(text, [(t.code, t.detect_keywords or []) for t in types])
        ctype = next((t for t in types if t.code == code), None)
        job.contract_type_code, job.type_detected = (ctype.code if ctype else None), ctype is not None

    clauses = analysis.segment(text)
    for c in clauses:
        c.category = analysis.classify(c.text)
        c.extracted = analysis.extract(c.text)

    await db.execute(delete(ScanFinding).where(ScanFinding.job_id == job.id))
    active = await rules.active_rules(db, ctype.id if ctype else None)
    base_ctx = {"contract": {"type": ctype.code if ctype else None}, "side": job.side}
    rule_findings = engine.run_clauses(active, [c.as_ctx() for c in clauses], base_ctx)

    rows: list[ScanFinding] = []
    flagged: set[int] = set()
    for f in rule_findings:
        clause = clauses[f.clause_index or 0]
        flagged.add(clause.index)
        kind = {"red": FindingKind.ILLEGAL, "yellow": FindingKind.RISKY}.get(f.severity.value, FindingKind.ADVICE)
        row = ScanFinding(
            job_id=job.id,
            clause_index=clause.index,
            clause_text=clause.text,
            category=clause.category,
            kind=kind,
            severity=f.severity.value,
            rule_code=f.rule_code,
            law_ref=f.law_ref,
            explanation=f.message,
            suggestion=f.fix_suggestion,
            extracted=clause.extracted,
        )
        rows.append(row)

    for c in clauses:
        dr = analysis.duty_or_right(c.text)
        if dr is None:
            continue
        rows.append(
            ScanFinding(
                job_id=job.id,
                clause_index=c.index,
                clause_text=c.text,
                category=c.category,
                kind=FindingKind.DUTY if dr == "duty" else FindingKind.RIGHT,
                severity=None,
                explanation=(
                    "Siz quyidagini bajarishingiz kerak bo'lishi mumkin"
                    if dr == "duty"
                    else "Siz quyidagi huquqqa egasiz"
                ),
                extracted=c.extracted,
            )
        )

    missing = analysis.missing_elements(text, ctype.required_elements or []) if ctype else []
    for el in missing:
        rows.append(
            ScanFinding(
                job_id=job.id,
                kind=FindingKind.MISSING,
                severity="yellow",
                rule_code=f"MISSING_{el['code'].upper()}",
                law_ref=el.get("law_ref"),
                explanation=f"Majburiy element topilmadi: {el['title']}",
                suggestion=el.get("suggestion"),
            )
        )
    template_check = None
    ref = reference_for(ctype)
    if ref is not None and ctype is not None:
        if ref.kind == "lexuz":
            template_check = ai.compare_with_template([c.text for c in clauses], ctype.template)
            where, law_ref = "Rasmiy namunaviy shakldagi", ctype.source.get("document_title")
            advice = "Bandni lex.uz'dagi rasmiy shaklga muvofiq qo'shing yoki yurist bilan maslahatlashing."
        else:
            template_check = ai.compare_with_template([c.text for c in clauses], ref.as_template(), granular=True)
            where, law_ref = "Tashkilot shablonidagi", ref.source.get("title")
            advice = "Bandni tashkilot tasdiqlagan shablonga muvofiq qo'shing yoki farqni yurist bilan kelishing."
        template_check["source"] = {"kind": ref.kind, "label": ref.label, **ref.source}
        for miss in template_check["missing"]:
            rows.append(
                ScanFinding(
                    job_id=job.id,
                    kind=FindingKind.MISSING,
                    source="template",
                    severity="yellow",
                    rule_code=f"TEMPLATE_{str(miss['key']).upper().replace(':', '_').replace('.', '_')}"[:64],
                    law_ref=law_ref,
                    explanation=f"{where} band topilmadi: {miss['title']}",
                    suggestion=advice,
                )
            )
    db.add_all(rows)

    red = sum(1 for r in rows if r.kind == FindingKind.ILLEGAL)
    yellow = sum(1 for r in rows if r.kind == FindingKind.RISKY)
    job.risk_level, job.risk_score = analysis.risk(red, yellow, len(missing))
    job.clauses_count = len(clauses)
    job.summary = {
        "red": red,
        "yellow": yellow,
        "missing": len(missing),
        "duties": sum(1 for r in rows if r.kind == FindingKind.DUTY),
        "rights": sum(1 for r in rows if r.kind == FindingKind.RIGHT),
        "contract_type": job.contract_type_code,
        "contract_type_title": ctype.title_uz if ctype else None,
        "document_title": analysis.document_title(text),
        "type_detected": job.type_detected,
        "categories": sorted({c.category for c in clauses if c.category}),
        "template_check": template_check,
    }
    job.ai_status = "pending" if llm.is_enabled() else "disabled"
    job.ai_summary = {}
    job.status, job.analyzed_at, job.error = ScanStatus.DONE, utcnow(), None
    await db.flush()


async def _document_info(db: AsyncSession, job: ScanJob) -> dict[str, Any]:
    """Which contract this report is about: its own heading, the detected type and the uploaded file."""
    summ = job.summary or {}
    type_title = summ.get("contract_type_title")
    if type_title is None and job.contract_type_code:
        ctype = await db.scalar(select(ContractType).where(ContractType.code == job.contract_type_code))
        type_title = ctype.title_uz if ctype else None
    title = summ.get("document_title") if "document_title" in summ else analysis.document_title(job.ocr_text or "")
    filename = None
    if job.file_id:
        from app.modules.files.models import StoredFile

        f = await db.get(StoredFile, job.file_id)
        filename = f.original_name if f else None
    return {
        "title": title or type_title or filename or "Shartnoma",
        "heading": title,
        "type_code": job.contract_type_code,
        "type_title": type_title,
        "type_detected": job.type_detected,
        "filename": filename,
        "clauses": job.clauses_count,
    }


async def report(db: AsyncSession, job: ScanJob) -> dict[str, Any]:
    if job.status != ScanStatus.DONE:
        return {"id": str(job.id), "status": job.status.value, "error": job.error, "ocr_confidence": job.ocr_confidence}
    findings = list(
        await db.scalars(
            select(ScanFinding).where(ScanFinding.job_id == job.id).order_by(ScanFinding.clause_index.nulls_last())
        )
    )

    def view(f: ScanFinding) -> dict[str, Any]:
        return {
            "id": str(f.id),
            "clause_index": f.clause_index,
            "clause_text": f.clause_text,
            "category": f.category,
            "severity": f.severity,
            "rule_code": f.rule_code,
            "law_ref": f.law_ref,
            "explanation": f.explanation,
            "suggestion": f.suggestion,
            "extracted": f.extracted,
            "source": f.source,
            "ai_explanation": f.ai_explanation,
            "ai_confidence": f.ai_confidence,
            "needs_lawyer": f.ai_confidence is not None
            and (f.ai_confidence < 0.6 or (f.extracted or {}).get("ai_severity") == "red"),
            "user_decision": f.user_decision.value if f.user_decision else None,
        }

    by_kind: dict[FindingKind, list[dict[str, Any]]] = {k: [] for k in FindingKind}
    for f in findings:
        by_kind[f.kind].append(view(f))
    cards = [v for k in (FindingKind.ILLEGAL, FindingKind.RISKY) for v in by_kind[k]]
    return {
        "id": str(job.id),
        "status": job.status.value,
        "document": await _document_info(db, job),
        "overall": {
            "risk_level": job.risk_level,
            "risk_score": job.risk_score,
            "risk_percent": analysis.risk_percent(job.risk_level, job.risk_score),
            "risk_label": analysis.RISK_LABELS.get(job.risk_level or "", ""),
            **job.summary,
        },
        "red_clauses": by_kind[FindingKind.ILLEGAL],
        "risky_clauses": by_kind[FindingKind.RISKY],
        "your_obligations": by_kind[FindingKind.DUTY],
        "your_rights": by_kind[FindingKind.RIGHT],
        "missing_elements": by_kind[FindingKind.MISSING],
        "advice": by_kind[FindingKind.ADVICE],
        "agree_cards": [
            {
                "finding_id": c["id"],
                "clause_text": c["clause_text"],
                "question": "Rozimisiz?",
                "alternative": c["suggestion"],
                "decision": c["user_decision"],
            }
            for c in cards
        ],
        "ocr": {"method": job.extraction, "confidence": job.ocr_confidence, "confirmed": job.text_confirmed},
        "ai": {"status": job.ai_status or "disabled", **(job.ai_summary or {})},
        "disclaimer": "Hisobot avtomatlashtirilgan tahlil natijasi; murakkab holatlarda yurist bilan maslahatlashing.",
    }


async def decide(db: AsyncSession, job: ScanJob, finding_id: uuid.UUID, decision: Decision) -> ScanFinding:
    f = await db.get(ScanFinding, finding_id)
    if f is None or f.job_id != job.id:
        raise NotFound("Finding not found")
    f.user_decision, f.decided_at = decision, utcnow()
    return f


async def obligations_from_scan(db: AsyncSession, job: ScanJob, user: User) -> list[uuid.UUID]:
    """Create *unconfirmed* obligations from dated duties; the user confirms each (spec §5.6).

    AI-extracted obligations (who / what / when / how much) are used when available; otherwise
    the deterministic date/amount extraction of duty clauses.
    """
    ai_obs = [o for o in (job.ai_summary or {}).get("obligations", []) if o.get("due_date")]
    if ai_obs:
        created_ai: list[uuid.UUID] = []
        for o in ai_obs:
            who = f"{o['who']}: " if o.get("who") else ""
            ob = await obligations.create(
                db,
                owner_id=user.id,
                title=f"{who}{o['title']}"[:255],
                due_date=date.fromisoformat(o["due_date"]),
                kind=ObligationKind.DUTY,
                source=ObligationSource.SCAN,
                confirmed=False,
                contract_id=job.contract_id,
                amount=Decimal(str(o["amount"])) if o.get("amount") is not None else None,
                currency=o.get("currency") or "UZS",
                recurrence_rule="FREQ=MONTHLY" if o.get("recurring") == "monthly" else None,
                description=f"AI ajratdi (ishonch {o.get('confidence', 0):.0%}). Tasdiqlashdan oldin tekshiring.",
                source_clause_ref=f"scan:{job.id}:{o.get('clause_index')}",
            )
            created_ai.append(ob.id)
        return created_ai
    duties = await db.scalars(
        select(ScanFinding).where(ScanFinding.job_id == job.id, ScanFinding.kind == FindingKind.DUTY)
    )
    created: list[uuid.UUID] = []
    for f in duties:
        dates = (f.extracted or {}).get("dates") or []
        if not dates:
            continue
        amounts = (f.extracted or {}).get("amounts") or []
        ob = await obligations.create(
            db,
            owner_id=user.id,
            title=(f.clause_text or "Majburiyat")[:120],
            due_date=date.fromisoformat(dates[0]),
            kind=ObligationKind.DUTY,
            source=ObligationSource.SCAN,
            confirmed=False,
            contract_id=job.contract_id,
            amount=Decimal(str(amounts[0]["value"])) if amounts else None,
            currency=amounts[0]["currency"] if amounts else "UZS",
            recurrence_rule="FREQ=MONTHLY" if (f.extracted or {}).get("recurring") == "monthly" else None,
            source_clause_ref=f"scan:{job.id}:{f.clause_index}",
        )
        created.append(ob.id)
    return created


# --- AI review (background) --------------------------------------------------------------------


def _ai_finding(job: ScanJob, issue: ai.AIIssue, clause_text: str | None) -> ScanFinding:
    # In the scanner (analysis only, nothing is blocked) a confident «contrary to law» verdict of the
    # model is shown as illegal; in the contract builder only the rule engine can block generation.
    illegal = issue.ai_severity == "red" and issue.confidence >= get_settings().llm_min_confidence
    if illegal:
        kind, severity, prefix = FindingKind.ILLEGAL, "red", "AI: "
    else:
        kind = FindingKind.RISKY if issue.severity == "yellow" else FindingKind.ADVICE
        severity = issue.severity
        prefix = "AI: ehtimoliy qonunbuzarlik — yurist tekshirsin. " if issue.ai_severity == "red" else "AI: "
    return ScanFinding(
        job_id=job.id,
        clause_index=issue.clause_index,
        clause_text=clause_text,
        kind=kind,
        source="ai",
        severity=severity,
        rule_code=None,
        law_ref=issue.law_ref,
        explanation=f"{prefix}{issue.title}. {issue.explanation}".strip(),
        suggestion=issue.suggestion,
        ai_explanation=issue.explanation,
        ai_confidence=issue.confidence,
        extracted={"ai_severity": issue.ai_severity},
    )


async def ai_review(job_id: uuid.UUID) -> None:
    """LLM pass after the deterministic analysis: extra risks, obligations, template deviations."""
    async with session_scope() as db:
        job = await db.get(ScanJob, job_id)
        if job is None or job.status != ScanStatus.DONE or not job.ocr_text:
            return
        clauses = analysis.segment(job.ocr_text)
        clause_ctx = [{"index": c.index, "text": c.text} for c in clauses]
        rule_rows = list(
            await db.scalars(
                select(ScanFinding).where(
                    ScanFinding.job_id == job.id,
                    ScanFinding.source != "ai",
                    ScanFinding.kind.in_([FindingKind.ILLEGAL, FindingKind.RISKY, FindingKind.MISSING]),
                )
            )
        )
        ctype = (
            await db.scalar(select(ContractType).where(ContractType.code == job.contract_type_code))
            if job.contract_type_code
            else None
        )
        ref = reference_for(ctype)
        try:
            result = await ai.review(
                clauses=clause_ctx,
                contract_type=ctype.title_uz if ctype else job.contract_type_code,
                rule_findings=[{"clause_index": r.clause_index, "message": r.explanation} for r in rule_rows],
                template_clauses=ref.texts if ref else None,
                template_label=ref.label if ref else None,
                law_texts=contracts_service.laws_for_type(ctype),
            )
        except AppError as e:
            job.ai_status, job.ai_summary = "failed", {"error": e.code, "message": e.message}
            log.warning("ai_review_failed", extra={"job_id": str(job_id), "error": e.code})
            return
        await db.execute(delete(ScanFinding).where(ScanFinding.job_id == job.id, ScanFinding.source == "ai"))
        ai_rows = []
        for issue in result.issues:
            text = clauses[issue.clause_index].text if issue.clause_index is not None else None
            ai_rows.append(_ai_finding(job, issue, text))
            db.add(ai_rows[-1])
        # overall risk now also reflects what the AI found (it can only go up)
        kinds = [r.kind for r in rule_rows] + [r.kind for r in ai_rows]
        level, score = analysis.risk(
            kinds.count(FindingKind.ILLEGAL), kinds.count(FindingKind.RISKY), kinds.count(FindingKind.MISSING)
        )
        if score > (job.risk_score or 0):
            job.risk_level, job.risk_score = level, score
        data = result.to_dict()
        job.ai_status, job.ai_summary = (
            "done",
            {k: v for k, v in data.items() if k != "issues"} | {"issues_count": len(result.issues)},
        )
        owner = await db.get(User, job.owner_id)
        if owner is not None:
            await channels.notify(
                db,
                owner,
                channels.Message(
                    type="scan.ai_ready",
                    title="AI tahlili tayyor",
                    body=(
                        f"{len(result.issues)} ta qo'shimcha ogohlantirish, "
                        f"{len(result.obligations)} ta majburiyat topildi."
                    ),
                    payload={"scan_id": str(job.id)},
                ),
                channels=["in_app"],
            )
        await audit.record(
            db,
            action="scan.ai_review",
            entity="scan_job",
            entity_id=job.id,
            actor_id=None,
            meta={
                "model": result.model,
                "issues": len(result.issues),
                "masked": result.masked,
                "latency_ms": result.latency_ms,
            },
        )


async def ask(db: AsyncSession, job: ScanJob, question: str) -> dict[str, Any]:
    if job.status != ScanStatus.DONE or not job.ocr_text:
        raise ValidationFailed("Scan is not analysed yet", code="scan_not_done")
    clauses = [{"index": c.index, "text": c.text} for c in analysis.segment(job.ocr_text)]
    rows = await db.scalars(select(ScanFinding).where(ScanFinding.job_id == job.id, ScanFinding.severity.is_not(None)))
    ctype = (
        await db.scalar(select(ContractType).where(ContractType.code == job.contract_type_code))
        if job.contract_type_code
        else None
    )
    return await ai.ask(
        clauses=clauses,
        findings=[f"[{r.clause_index}] {r.explanation}" for r in rows],
        question=question,
        contract_type=ctype.title_uz if ctype else None,
        law_texts=contracts_service.law_context(ctype, question),
    )
