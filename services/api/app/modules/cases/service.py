from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime
from typing import Any

from docx import Document
from docx.shared import Pt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import canonical_json, sha256_hex
from app.core.errors import Forbidden, NotFound
from app.core.timeutils import ensure_utc, to_local, utcnow
from app.db.session import session_scope
from app.modules.anchoring import hooks as anchor_hooks
from app.modules.anchoring import service as anchoring
from app.modules.anchoring.models import LeafKind
from app.modules.audit import service as audit
from app.modules.cases.models import AttachmentType, CaseAttachment, CaseFile, CaseStatus, CaseStep
from app.modules.contracts.models import Contract
from app.modules.files import service as files
from app.modules.notifications import channels
from app.modules.users.models import User, UserRole

_MIME_TYPE = {"application/pdf": AttachmentType.PDF, "audio/": AttachmentType.AUDIO, "image/": AttachmentType.IMAGE}


def _att_type(mime: str, declared: AttachmentType | None) -> AttachmentType:
    if declared:
        return declared
    for prefix, t in _MIME_TYPE.items():
        if mime.startswith(prefix):
            return t
    return AttachmentType.DOCUMENT


async def create(
    db: AsyncSession,
    lawyer: User,
    *,
    title: str,
    contract_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    client_name: str | None,
    tags: list[str],
) -> CaseFile:
    if lawyer.role not in (UserRole.LAWYER, UserRole.ADMIN):
        raise Forbidden("Only verified lawyers can open case files", code="lawyer_only")
    if contract_id:
        c = await db.get(Contract, contract_id)
        if c is None or not (c.owner_id == lawyer.id or any(p.user_id == lawyer.id for p in c.parties)):
            raise NotFound("Contract not found")
    case = CaseFile(
        lawyer_id=lawyer.id,
        title=title,
        contract_id=contract_id,
        client_id=client_id,
        client_name=client_name,
        tags=tags,
    )
    db.add(case)
    await db.flush()
    await audit.record(db, action="case.create", entity="case_file", entity_id=case.id, actor_id=lawyer.id)
    return case


async def load(db: AsyncSession, case_id: uuid.UUID, user: User, *, write: bool = False) -> CaseFile:
    case = await db.get(CaseFile, case_id)
    if case is None:
        raise NotFound("Case not found")
    if case.lawyer_id == user.id:
        return case
    if not write and case.shared_with_client and case.client_id == user.id:
        return case
    raise NotFound("Case not found")


async def list_for(
    db: AsyncSession, user: User, *, status: CaseStatus | None, tag: str | None, q: str | None, limit: int, offset: int
) -> list[CaseFile]:
    stmt = select(CaseFile).where(
        or_(CaseFile.lawyer_id == user.id, (CaseFile.client_id == user.id) & CaseFile.shared_with_client.is_(True))
    )
    if status:
        stmt = stmt.where(CaseFile.status == status)
    if q:
        stmt = stmt.where(CaseFile.title.ilike(f"%{q}%"))
    rows = list(
        await db.scalars(stmt.order_by(CaseFile.updated_at.desc()).limit(limit * 3 if tag else limit).offset(offset))
    )
    if tag:  # JSON array filtering kept portable (SQLite + Postgres)
        rows = [r for r in rows if tag in (r.tags or [])][:limit]
    return rows


async def add_step(
    db: AsyncSession,
    case: CaseFile,
    user: User,
    *,
    title: str,
    description: str | None,
    step_at: datetime | None,
    tags: list[str],
    obligation_id: uuid.UUID | None,
) -> CaseStep:
    step = CaseStep(
        case_file_id=case.id,
        title=title,
        description=description,
        step_at=step_at or utcnow(),
        tags=tags,
        obligation_id=obligation_id,
        created_by=user.id,
    )
    db.add(step)
    case.updated_at = utcnow()
    await db.flush()
    await audit.record(
        db, action="case.step", entity="case_file", entity_id=case.id, actor_id=user.id, meta={"step_id": str(step.id)}
    )
    return step


async def add_attachment(
    db: AsyncSession,
    case: CaseFile,
    user: User,
    *,
    step_id: uuid.UUID,
    data: bytes,
    filename: str,
    mime: str | None,
    type_: AttachmentType | None,
    note: str | None,
) -> CaseAttachment:
    step = await db.get(CaseStep, step_id)
    if step is None or step.case_file_id != case.id:
        raise NotFound("Step not found")
    stored = await files.save_bytes(
        db, data=data, filename=filename, declared_mime=mime, owner_id=user.id, purpose="case"
    )
    att = CaseAttachment(
        step_id=step.id,
        file_id=stored.id,
        type=_att_type(stored.mime, type_),
        sha256=stored.sha256,
        captured_at=utcnow(),
        note=note,
    )
    db.add(att)
    await db.flush()
    await anchor_hooks.case_attachment(db, attachment=att, case_id=case.id)
    await audit.record(
        db,
        action="case.attachment",
        entity="case_file",
        entity_id=case.id,
        actor_id=user.id,
        meta={"file_id": str(stored.id), "sha256": stored.sha256},
    )
    return att


def _timeline_docx(case: CaseFile, manifest: dict[str, Any]) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(f"Dalillar to'plami: {case.title}", level=1)
    doc.add_paragraph(f"Yaratilgan: {manifest['generated_at']}  •  Manifest SHA-256: {manifest['manifest_sha256']}")
    for s in manifest["steps"]:
        doc.add_heading(f"{s['step_at_local']} — {s['title']}", level=2)
        if s.get("description"):
            doc.add_paragraph(s["description"])
        for a in s["attachments"]:
            doc.add_paragraph(f"• {a['path']} ({a['type']}), SHA-256: {a['sha256']}, qayd vaqti: {a['captured_at']}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def _anchor_or_none(db: AsyncSession, attachment_id: uuid.UUID) -> dict[str, Any] | None:
    """Blockchain proof for an evidence file (None if it was never queued for anchoring)."""
    try:
        return await anchoring.proof_package(db, kind=LeafKind.CASE_ATTACHMENT, ref_id=attachment_id)
    except NotFound:
        return None


async def export_zip(db: AsyncSession, case: CaseFile, user: User) -> tuple[bytes, str]:
    """Chronological evidence bundle: files + manifest with hashes + timeline DOCX."""
    buf = io.BytesIO()
    steps_view = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, step in enumerate(sorted(case.steps, key=lambda s: ensure_utc(s.step_at)), start=1):
            atts = []
            for j, att in enumerate(step.attachments, start=1):
                row = await files.get_file(db, att.file_id)
                data = await files.read_bytes(row)  # verifies integrity
                path = f"files/{i:03d}-{j:02d}-{row.original_name}"
                zf.writestr(path, data)
                atts.append(
                    {
                        "path": path,
                        "type": att.type.value,
                        "sha256": att.sha256,
                        "captured_at": ensure_utc(att.captured_at).isoformat(),
                        "note": att.note,
                        "blockchain": await _anchor_or_none(db, att.id),
                    }
                )
            steps_view.append(
                {
                    "no": i,
                    "step_at": ensure_utc(step.step_at).isoformat(),
                    "step_at_local": to_local(step.step_at).strftime("%d.%m.%Y %H:%M"),
                    "title": step.title,
                    "description": step.description,
                    "tags": step.tags,
                    "attachments": atts,
                }
            )
        manifest: dict[str, Any] = {
            "case_id": str(case.id),
            "title": case.title,
            "status": case.status.value,
            "contract_id": str(case.contract_id) if case.contract_id else None,
            "generated_at": utcnow().isoformat(),
            "generated_by": str(user.id),
            "steps": steps_view,
        }
        manifest["manifest_sha256"] = sha256_hex(canonical_json({k: v for k, v in manifest.items()}))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("timeline.docx", _timeline_docx(case, manifest))
    await audit.record(
        db,
        action="case.export",
        entity="case_file",
        entity_id=case.id,
        actor_id=user.id,
        meta={"manifest_sha256": manifest["manifest_sha256"]},
    )
    return buf.getvalue(), manifest["manifest_sha256"]


async def build_export_job(case_id: str, user_id: str) -> None:
    """Background variant for large archives: stores the ZIP and notifies the lawyer."""
    async with session_scope() as db:
        user = await db.get(User, uuid.UUID(user_id))
        case = await db.get(CaseFile, uuid.UUID(case_id))
        if user is None or case is None:
            return
        data, digest = await export_zip(db, case, user)
        stored = await files.save_bytes(
            db,
            data=data,
            filename=f"case-{case.id.hex[:8]}.zip",
            declared_mime="application/zip",
            owner_id=user.id,
            purpose="export",
        )
        await channels.notify(
            db,
            user,
            channels.Message(
                type="case.export_ready",
                title="Dalillar to'plami tayyor",
                body=case.title,
                payload={"file_id": str(stored.id), "manifest_sha256": digest},
            ),
            channels=["in_app"],
        )
