from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import delete, select

from app.api.deps import DB, CurrentUser, PageParams
from app.core.config import get_settings
from app.core.errors import Conflict, ValidationFailed
from app.core.ratelimit import get_limiter
from app.modules.files import service as files
from app.modules.files.models import StoredFile
from app.modules.scan import analysis, report_docx, service
from app.modules.scan.models import Decision, ScanFinding, ScanJob, ScanStatus
from app.workers import queue

router = APIRouter(prefix="/scans", tags=["scan"])


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: ScanStatus
    ai_status: str | None = None
    contract_type_code: str | None
    type_detected: bool
    extraction: str | None
    ocr_confidence: float | None
    text_confirmed: bool
    risk_level: str | None
    risk_score: float | None
    summary: dict[str, Any]
    error: str | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_percent(self) -> int:
        """0..100 for the risk gauge (banded by risk_level)."""
        return analysis.risk_percent(self.risk_level, self.risk_score)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def title(self) -> str | None:
        """The contract's own name (heading) or its detected type — for history lists."""
        s = self.summary or {}
        return s.get("document_title") or s.get("contract_type_title")


class ScanText(BaseModel):
    text: str = Field(min_length=50, max_length=300_000)


class DecisionIn(BaseModel):
    decision: Decision


@router.post("", response_model=ScanOut, status_code=status.HTTP_202_ACCEPTED, summary="Fayl yuklash: OCR + tahlil")
async def create_scan(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    contract_type_code: str | None = Form(default=None),
    side: Literal["A", "B"] | None = Form(default=None),
) -> ScanOut:
    await get_limiter().hit(f"scan:{user.id}", limit=30, window_s=3600)
    data = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    job = await service.create_job(
        db,
        user=user,
        data=data,
        filename=file.filename or "document",
        mime=file.content_type,
        contract_type_code=contract_type_code,
        side=side,
    )
    await db.commit()  # the worker must see the row
    await queue.enqueue("process_scan", job.id)
    return ScanOut.model_validate(job)


@router.post(
    "/text",
    response_model=ScanOut,
    status_code=status.HTTP_201_CREATED,
    summary="Matnni to'g'ridan-to'g'ri tekshirish (fayl o'rniga)",
)
async def scan_text(
    body: ScanText,
    db: DB,
    user: CurrentUser,
    contract_type_code: str | None = None,
    side: Literal["A", "B"] | None = None,
) -> ScanOut:
    job = await service.create_job(
        db,
        user=user,
        data=body.text.encode(),
        filename="text.txt",
        mime="text/plain",
        contract_type_code=contract_type_code,
        side=side,
    )
    job.ocr_text, job.extraction, job.text_confirmed = body.text, "plain", True
    await service.analyze(db, job)
    out = ScanOut.model_validate(job)
    await db.commit()  # the AI job must see the stored analysis
    await service.queue_ai_review(job.id)
    return out


@router.get("", response_model=list[ScanOut])
async def list_scans(db: DB, user: CurrentUser, page: PageParams) -> list[ScanOut]:
    rows = await db.scalars(
        select(ScanJob)
        .where(ScanJob.owner_id == user.id)
        .order_by(ScanJob.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return [ScanOut.model_validate(j) for j in rows]


@router.get("/{scan_id}", response_model=ScanOut)
async def get_scan(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> ScanOut:
    return ScanOut.model_validate(await service.get_owned(db, scan_id, user))


@router.get("/{scan_id}/text", summary="Tanib olingan matn (tasdiqlash/tuzatish uchun)")
async def get_text(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    job = await service.get_owned(db, scan_id, user)
    return {"text": job.ocr_text, "confidence": job.ocr_confidence, "confirmed": job.text_confirmed}


@router.put("/{scan_id}/text", response_model=ScanOut, summary="OCR matnini tasdiqlash/tuzatish va qayta tahlil")
async def put_text(scan_id: uuid.UUID, body: ScanText, db: DB, user: CurrentUser) -> ScanOut:
    job = await service.get_owned(db, scan_id, user)
    out = ScanOut.model_validate(await service.confirm_text(db, job, body.text))
    await db.commit()
    await service.queue_ai_review(job.id)
    return out


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post(
    "/{scan_id}/ai/review", status_code=status.HTTP_202_ACCEPTED, summary="AI tahlilini (qayta) ishga tushirish"
)
async def ai_rerun(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, str]:
    job = await service.get_owned(db, scan_id, user)
    if job.status != ScanStatus.DONE:
        raise ValidationFailed("Scan is not analysed yet", code="scan_not_done")
    await get_limiter().hit(f"ai:{user.id}", limit=40, window_s=3600)
    await db.commit()
    await service.queue_ai_review(job.id)
    return {"ai_status": "pending"}


@router.post("/{scan_id}/ai/ask", summary="Shartnoma bo'yicha AI'ga savol (faqat shu matnga tayanadi)")
async def ai_ask(scan_id: uuid.UUID, body: AskIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    job = await service.get_owned(db, scan_id, user)
    await get_limiter().hit(f"ai:{user.id}", limit=40, window_s=3600)
    return await service.ask(db, job, body.question)


@router.get("/{scan_id}/report", summary="Hisobot")
async def get_report(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await service.report(db, await service.get_owned(db, scan_id, user))


@router.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Tahlilni va yuklangan faylni o'chirish")
async def delete_scan(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    job = await service.get_owned(db, scan_id, user)
    file_id = job.file_id
    await db.execute(delete(ScanFinding).where(ScanFinding.job_id == job.id))
    await db.delete(job)
    await db.flush()
    if file_id:
        await files.delete_file(db, file_id)


@router.get("/{scan_id}/report/download", summary="Hisobotni DOCX ko'rinishida yuklab olish")
async def download_report(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    job = await service.get_owned(db, scan_id, user)
    rep = await service.report(db, job)
    if rep.get("status") != ScanStatus.DONE.value:
        raise Conflict("Analysis is not finished yet", code="scan_not_done")
    title = "Matn orqali yuborilgan shartnoma"
    if job.file_id:
        f = await db.get(StoredFile, job.file_id)
        if f is not None:
            title = f.original_name
    data = report_docx.build(rep, title=title, created_at=job.created_at.isoformat())
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="tahlil-{str(job.id)[:8]}.docx"'},
    )


@router.post("/{scan_id}/findings/{finding_id}/decision", summary="Rozi / e'tiroz")
async def decide(
    scan_id: uuid.UUID, finding_id: uuid.UUID, body: DecisionIn, db: DB, user: CurrentUser
) -> dict[str, Any]:
    job = await service.get_owned(db, scan_id, user)
    f = await service.decide(db, job, finding_id, body.decision)
    return {
        "finding_id": str(f.id),
        "decision": f.user_decision,
        "alternative": f.suggestion if body.decision == Decision.OBJECT else None,
    }


@router.post("/{scan_id}/obligations", summary="Sanali majburiyatlarni eslatmaga aylantirish (tasdiqlanmagan)")
async def to_obligations(scan_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    job = await service.get_owned(db, scan_id, user)
    if job.status != ScanStatus.DONE:
        raise ValidationFailed("Scan is not analysed yet", code="scan_not_done")
    ids = await service.obligations_from_scan(db, job, user)
    return {"created": [str(i) for i in ids], "note": "Har bir majburiyatni tasdiqlang (confirmed=true)."}
