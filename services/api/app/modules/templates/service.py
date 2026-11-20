"""Contract templates sourced from official lex.uz model forms.

import  -> draft TemplateVersion (with provenance + converter report)
approve -> four-eyes; dry-run render; applied to ContractType (previous version kept as superseded)
monitor -> daily: re-fetch sources; edition change / loss of force => editor task + needs_review flag
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound, ValidationFailed
from app.core.timeutils import utcnow
from app.integrations import lexuz
from app.modules.audit import service as audit
from app.modules.contracts import generator
from app.modules.contracts.models import ContractType, FormRequirement
from app.modules.moderation.models import ContentTask
from app.modules.templates import converter
from app.modules.templates.models import TemplateStatus, TemplateVersion
from app.modules.users.models import User

log = logging.getLogger(__name__)


def _content_dir() -> Path:
    p = Path(get_settings().legal_content_dir)
    return p if p.is_absolute() else (Path(__file__).resolve().parents[3] / p).resolve()


@lru_cache
def profiles() -> dict[str, Any]:
    path = _content_dir() / "importers" / "lexuz_profiles.json"
    return json.loads(path.read_text(encoding="utf-8"))


def find_profile(doc_id: str, annex: int | None) -> dict[str, Any] | None:
    for p in profiles().get("profiles", []):
        if str(p.get("doc_id")) == str(doc_id) and (annex is None or p.get("annex") == annex):
            return p
    return None


def annex_hash(annex: lexuz.Annex) -> str:
    return hashlib.sha256(annex.text.encode()).hexdigest()


async def preview_document(doc_id: str, lang: str = "uz") -> dict[str, Any]:
    doc = await lexuz.fetch(doc_id, lang=lang)
    return {
        "doc_id": doc.doc_id,
        "url": doc.url,
        "title": doc.title,
        "header": doc.header,
        "in_force_from": doc.in_force_from,
        "edition_date": doc.edition_date,
        "lost_force": doc.lost_force,
        "lost_force_date": doc.lost_force_date,
        "annexes": [
            {
                "number": a.number,
                "title": a.title,
                "has_blanks": "___" in a.text,
                "profile": (find_profile(doc.doc_id, a.number) or {}).get("id"),
            }
            for a in doc.annexes
        ],
    }


def sample_answers(questionnaire: dict[str, Any]) -> dict[str, Any]:
    """Dummy values for every field — used to dry-run a template before approval."""
    answers: dict[str, Any] = {}
    for sec in questionnaire.get("sections", []):
        for f in sec.get("fields", []):
            value: Any = {"number": 1, "date": "2026-01-01", "boolean": True}.get(f.get("type"), "X")
            if f.get("type") == "enum" and f.get("options"):
                opt = f["options"][0]
                value = opt["value"] if isinstance(opt, dict) else opt
            cur = answers
            parts = f["key"].split(".")
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = value
    return answers


def dry_run(tv: TemplateVersion) -> None:
    answers = sample_answers(tv.questionnaire)
    for tpl in filter(None, (tv.template, tv.template_ru)):
        generator.render_content(
            template=tpl,
            answers=answers,
            extra_clauses=[],
            type_code=tv.contract_type_code,
            language="uz",
            form_requirement="simple",
        )


async def import_from_lexuz(
    db: AsyncSession,
    *,
    doc_id: str,
    annex_number: int | None,
    target_code: str | None,
    title: str | None,
    latin: bool,
    author: User | None,
) -> TemplateVersion:
    doc = await lexuz.fetch(doc_id, lang="uz")
    if doc.lost_force:
        raise ValidationFailed(
            f"lex.uz: hujjat kuchini yo'qotgan ({doc.lost_force_date}) — undan shablon olinmaydi",
            code="lexuz_lost_force",
        )
    profile = find_profile(doc.doc_id, annex_number)
    number = annex_number if annex_number is not None else (profile or {}).get("annex")
    annex = doc.annex(number=number) if number is not None else (doc.annexes[0] if doc.annexes else None)
    if annex is None or "___" not in annex.text:
        raise ValidationFailed("Ilovada to'ldiriladigan namunaviy shakl topilmadi", code="lexuz_no_form")
    conv = converter.convert(annex, profile, profiles().get("generic", []), latin=latin)
    code = target_code or (profile or {}).get("target") or f"lexuz_{doc.doc_id.lstrip('-')}_{annex.number or 1}"
    last = await db.scalar(
        select(TemplateVersion.version)
        .where(TemplateVersion.contract_type_code == code)
        .order_by(TemplateVersion.version.desc())
        .limit(1)
    )
    tv = TemplateVersion(
        contract_type_code=code,
        version=(last or 0) + 1,
        status=TemplateStatus.DRAFT,
        title_uz=title or (profile or {}).get("title_uz") or converter.cyr_to_lat(annex.title)[:255],
        description=(profile or {}).get("description") or f"{doc.title} — {annex.number}-ilova",
        questionnaire=conv.questionnaire,
        template=conv.template,
        source={
            "kind": "lexuz",
            "doc_id": doc.doc_id,
            "lang": doc.lang,
            "url": doc.url,
            "annex": annex.number,
            "annex_title": annex.title,
            "document_title": doc.title,
            "issuer": doc.header,
            "edition_date": doc.edition_date.isoformat() if doc.edition_date else None,
            "in_force_from": doc.in_force_from.isoformat() if doc.in_force_from else None,
            "annex_sha256": annex_hash(annex),
            "element_ids": [b.element_id for b in annex.blocks if b.element_id],
            "fetched_at": doc.fetched_at.isoformat(),
            "script": "latin" if latin else "cyrillic",
            "profile": (profile or {}).get("id"),
            "party_roles": (profile or {}).get("party_roles"),
        },
        original_text=conv.original_text,
        report=conv.report,
        author_id=author.id if author else None,
    )
    dry_run(tv)  # never store a template that can't render
    db.add(tv)
    await db.flush()
    await audit.record(
        db,
        action="template.import",
        entity="template_version",
        entity_id=tv.id,
        actor_id=author.id if author else None,
        meta={"doc_id": doc.doc_id, "annex": annex.number, "code": code, "report": conv.report},
    )
    return tv


async def get_version(db: AsyncSession, tv_id: uuid.UUID) -> TemplateVersion:
    tv = await db.get(TemplateVersion, tv_id)
    if tv is None:
        raise NotFound("Template version not found")
    return tv


async def update_draft(db: AsyncSession, tv: TemplateVersion, data: dict[str, Any], editor: User) -> TemplateVersion:
    if tv.status != TemplateStatus.DRAFT:
        raise Conflict("Only drafts can be edited", code="template_not_draft")
    for k in ("title_uz", "description", "questionnaire", "template", "template_ru"):
        if k in data and data[k] is not None:
            setattr(tv, k, data[k])
    dry_run(tv)
    tv.author_id = editor.id
    await audit.record(db, action="template.edit", entity="template_version", entity_id=tv.id, actor_id=editor.id)
    return tv


async def approve(
    db: AsyncSession, tv: TemplateVersion, approver: User | None, *, system: bool = False
) -> ContractType:
    if tv.status != TemplateStatus.DRAFT:
        raise Conflict("Only drafts can be approved", code="template_not_draft")
    if not system and approver is not None and tv.author_id == approver.id:
        raise Forbidden("Author cannot approve their own template", code="four_eyes")
    dry_run(tv)
    ctype = await db.scalar(select(ContractType).where(ContractType.code == tv.contract_type_code))
    if ctype is None:
        ctype = ContractType(
            code=tv.contract_type_code, title_uz=tv.title_uz, form_requirement=FormRequirement.SIMPLE, version=0
        )
        db.add(ctype)
    ctype.title_uz = tv.title_uz
    ctype.description = tv.description
    ctype.questionnaire = tv.questionnaire
    ctype.template = tv.template
    ctype.template_ru = tv.template_ru
    ctype.source = {**tv.source, "template_version": tv.version, "needs_review": False}
    ctype.version = (ctype.version or 0) + 1
    ctype.is_active = True
    for old in await db.scalars(
        select(TemplateVersion).where(
            TemplateVersion.contract_type_code == tv.contract_type_code,
            TemplateVersion.status == TemplateStatus.APPROVED,
            TemplateVersion.id != tv.id,
        )
    ):
        old.status = TemplateStatus.SUPERSEDED
    tv.status, tv.approved_at = TemplateStatus.APPROVED, utcnow()
    tv.approved_by = approver.id if approver else None
    await db.flush()
    await audit.record(
        db,
        action="template.approve",
        entity="contract_type",
        entity_id=ctype.id,
        actor_id=approver.id if approver else None,
        meta={"code": ctype.code, "template_version": tv.version, "system": system},
    )
    return ctype


async def reject(db: AsyncSession, tv: TemplateVersion, reviewer: User, note: str) -> TemplateVersion:
    if tv.status != TemplateStatus.DRAFT:
        raise Conflict("Only drafts can be rejected", code="template_not_draft")
    tv.status, tv.review_note = TemplateStatus.REJECTED, note
    await audit.record(
        db,
        action="template.reject",
        entity="template_version",
        entity_id=tv.id,
        actor_id=reviewer.id,
        meta={"note": note},
    )
    return tv


async def check_sources(db: AsyncSession) -> dict[str, Any]:
    """Re-fetch every lex.uz source; flag templates whose source changed or lost force."""
    result: dict[str, Any] = {"checked": 0, "changed": [], "lost_force": [], "errors": []}
    types = list(await db.scalars(select(ContractType).where(ContractType.source.is_not(None))))
    for ct in types:
        src = ct.source or {}
        if src.get("kind") != "lexuz":
            continue
        try:
            doc = await lexuz.fetch(src["doc_id"], lang=src.get("lang", "uz"))
        except AppError as e:
            result["errors"].append({"code": ct.code, "error": e.code})
            continue
        result["checked"] += 1
        reason = None
        if doc.lost_force:
            reason = f"lex.uz: manba hujjat kuchini yo'qotgan ({doc.lost_force_date})"
            result["lost_force"].append(ct.code)
        else:
            try:
                h = annex_hash(doc.annex(number=src.get("annex")))
            except NotFound:
                h = None
            if h != src.get("annex_sha256"):
                reason = (
                    f"lex.uz: namunaviy shakl o'zgargan (tahrir "
                    f"{doc.edition_date.isoformat() if doc.edition_date else '?'}) — shablonni qayta import qiling"
                )
                result["changed"].append(ct.code)
        if reason and not src.get("needs_review"):
            ct.source = {**src, "needs_review": True, "review_reason": reason, "checked_at": utcnow().isoformat()}
            db.add(
                ContentTask(
                    entity="contract_type",
                    entity_id=ct.id,
                    reason=reason,
                    meta={"doc_id": src["doc_id"], "url": src.get("url")},
                )
            )
        elif not reason:
            ct.source = {**src, "checked_at": utcnow().isoformat()}
    await db.flush()
    return result
