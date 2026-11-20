from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DB, CurrentUser, PageParams, require
from app.core.errors import NotFound
from app.core.rbac import Perm
from app.modules.anchoring import service as anchoring
from app.modules.anchoring.models import LeafKind
from app.modules.audit import service as audit
from app.modules.cases import service
from app.modules.cases.models import AttachmentType, CaseStatus
from app.modules.users.models import User
from app.workers import queue

router = APIRouter(prefix="/cases", tags=["lawyer archive"])
Lawyer = Annotated[User, Depends(require(Perm.CASES_USE))]


class CaseIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    contract_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    client_name: str | None = None
    tags: list[str] = Field(default_factory=list)


class CasePatch(BaseModel):
    title: str | None = None
    status: CaseStatus | None = None
    tags: list[str] | None = None
    shared_with_client: bool | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    file_id: uuid.UUID
    type: AttachmentType
    sha256: str
    captured_at: datetime
    note: str | None


class StepIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    step_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    obligation_id: uuid.UUID | None = None


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    step_at: datetime
    title: str
    description: str | None
    tags: list[str]
    obligation_id: uuid.UUID | None
    created_by: uuid.UUID
    attachments: list[AttachmentOut]


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    status: CaseStatus
    contract_id: uuid.UUID | None
    client_id: uuid.UUID | None
    client_name: str | None
    tags: list[str]
    shared_with_client: bool
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseOut):
    steps: list[StepOut]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED, summary="Ish yuritish ochish")
async def create_case(body: CaseIn, db: DB, user: Lawyer) -> CaseOut:
    return CaseOut.model_validate(await service.create(db, user, **body.model_dump()))


@router.get("", response_model=list[CaseOut])
async def list_cases(
    db: DB,
    user: CurrentUser,
    page: PageParams,
    status_: CaseStatus | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[CaseOut]:
    rows = await service.list_for(db, user, status=status_, tag=tag, q=q, limit=page.limit, offset=page.offset)
    return [CaseOut.model_validate(c) for c in rows]


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: uuid.UUID, db: DB, user: CurrentUser) -> CaseDetail:
    return CaseDetail.model_validate(await service.load(db, case_id, user))


@router.patch("/{case_id}", response_model=CaseOut, summary="Holat / nizo rejimi / mijozga ulashish")
async def patch_case(case_id: uuid.UUID, body: CasePatch, db: DB, user: Lawyer) -> CaseOut:
    case = await service.load(db, case_id, user, write=True)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(case, k, v)
    await audit.record(
        db,
        action="case.update",
        entity="case_file",
        entity_id=case.id,
        actor_id=user.id,
        meta={k: str(v) for k, v in changes.items()},
    )
    return CaseOut.model_validate(case)


@router.post("/{case_id}/steps", response_model=StepOut, status_code=status.HTTP_201_CREATED, summary="Qadam qo'shish")
async def add_step(case_id: uuid.UUID, body: StepIn, db: DB, user: Lawyer) -> StepOut:
    case = await service.load(db, case_id, user, write=True)
    step = await service.add_step(db, case, user, **body.model_dump())
    await db.refresh(step, ["attachments"])
    return StepOut.model_validate(step)


@router.post(
    "/{case_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Hujjat/rasm/audio yuklash (xesh + vaqt tamg'asi)",
)
async def add_attachment(
    case_id: uuid.UUID,
    db: DB,
    user: Lawyer,
    step_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    type_: AttachmentType | None = Form(default=None, alias="type"),
    note: str | None = Form(default=None),
) -> AttachmentOut:
    case = await service.load(db, case_id, user, write=True)
    att = await service.add_attachment(
        db,
        case,
        user,
        step_id=step_id,
        data=await file.read(),
        filename=file.filename or "file",
        mime=file.content_type,
        type_=type_,
        note=note,
    )
    return AttachmentOut.model_validate(att)


@router.get("/{case_id}/attachments/{attachment_id}/anchor", summary="Dalil faylining blokcheyn isboti")
async def attachment_anchor(case_id: uuid.UUID, attachment_id: uuid.UUID, db: DB, user: Lawyer) -> dict[str, Any]:
    case = await service.load(db, case_id, user, write=True)
    if not any(a.id == attachment_id for s in case.steps for a in s.attachments):
        raise NotFound("Attachment not found")
    return await anchoring.proof_package(db, kind=LeafKind.CASE_ATTACHMENT, ref_id=attachment_id)


@router.get("/{case_id}/export", summary="Dalil to'plami (ZIP: fayllar + manifest + timeline)")
async def export_case(case_id: uuid.UUID, db: DB, user: Lawyer) -> Response:
    case = await service.load(db, case_id, user, write=True)
    data, digest = await service.export_zip(db, case, user)
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="case-{case.id.hex[:8]}.zip"',
            "X-Manifest-SHA256": digest,
        },
    )


@router.post(
    "/{case_id}/export/async",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Katta arxiv uchun fon eksporti (tayyor bo'lganda bildirishnoma)",
)
async def export_case_async(case_id: uuid.UUID, db: DB, user: Lawyer) -> dict[str, str]:
    case = await service.load(db, case_id, user, write=True)
    await db.commit()
    await queue.enqueue("build_case_export", str(case.id), str(user.id))
    return {"status": "queued"}
