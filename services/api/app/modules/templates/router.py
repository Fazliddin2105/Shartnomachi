from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, PageParams, require
from app.core.rbac import Perm
from app.modules.templates import service
from app.modules.templates.models import TemplateStatus, TemplateVersion
from app.modules.users.models import User

router = APIRouter(prefix="/cms/templates", tags=["cms: lex.uz templates"])
Editor = Annotated[User, Depends(require(Perm.CONTRACT_TYPES_WRITE))]
Approver = Annotated[User, Depends(require(Perm.RULES_APPROVE))]


class ImportIn(BaseModel):
    doc_id: str = Field(examples=["7220862"], description="lex.uz hujjat ID (URL'dagi raqam, masalan -3532536)")
    annex: int | None = Field(default=None, description="Ilova raqami (namunaviy shakl joylashgan)")
    target_code: str | None = Field(
        default=None, pattern=r"^[a-z0-9_]{2,64}$", description="Qaysi shartnoma turiga qo'llanadi (masalan: labor)"
    )
    title: str | None = None
    latin: bool = Field(default=True, description="Kirill matnni lotinga o'girish")


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    contract_type_code: str
    version: int
    status: TemplateStatus
    title_uz: str
    description: str | None
    source: dict[str, Any]
    report: dict[str, Any]
    review_note: str | None
    created_at: datetime
    approved_at: datetime | None


class TemplateDetail(TemplateOut):
    questionnaire: dict[str, Any]
    template: dict[str, Any]
    template_ru: dict[str, Any] | None
    original_text: str | None


class TemplatePatch(BaseModel):
    title_uz: str | None = None
    description: str | None = None
    questionnaire: dict[str, Any] | None = None
    template: dict[str, Any] | None = None
    template_ru: dict[str, Any] | None = None


class RejectIn(BaseModel):
    note: str = Field(min_length=3)


@router.get("/lexuz/{doc_id}", summary="lex.uz hujjatini ko'rib chiqish: holati, tahriri, ilovalari")
async def lexuz_preview(doc_id: str, _: Editor, lang: str = "uz") -> dict[str, Any]:
    return await service.preview_document(doc_id, lang)


@router.post(
    "/import-lexuz",
    response_model=TemplateDetail,
    status_code=status.HTTP_201_CREATED,
    summary="lex.uz rasmiy namunaviy shaklidan shablon qoralamasini yaratish",
)
async def import_lexuz(body: ImportIn, db: DB, user: Editor) -> TemplateDetail:
    tv = await service.import_from_lexuz(
        db,
        doc_id=body.doc_id,
        annex_number=body.annex,
        target_code=body.target_code,
        title=body.title,
        latin=body.latin,
        author=user,
    )
    return TemplateDetail.model_validate(tv)


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    db: DB, _: Editor, page: PageParams, status_: TemplateStatus | None = None, code: str | None = None
) -> list[TemplateOut]:
    stmt = select(TemplateVersion).order_by(TemplateVersion.created_at.desc()).limit(page.limit).offset(page.offset)
    if status_:
        stmt = stmt.where(TemplateVersion.status == status_)
    if code:
        stmt = stmt.where(TemplateVersion.contract_type_code == code)
    return [TemplateOut.model_validate(t) for t in await db.scalars(stmt)]


@router.get("/{tv_id}", response_model=TemplateDetail)
async def get_template(tv_id: uuid.UUID, db: DB, _: Editor) -> TemplateDetail:
    return TemplateDetail.model_validate(await service.get_version(db, tv_id))


@router.put("/{tv_id}", response_model=TemplateDetail, summary="Qoralamani tahrirlash (maydon nomlari, turlari)")
async def update_template(tv_id: uuid.UUID, body: TemplatePatch, db: DB, user: Editor) -> TemplateDetail:
    tv = await service.get_version(db, tv_id)
    return TemplateDetail.model_validate(await service.update_draft(db, tv, body.model_dump(exclude_unset=True), user))


@router.post("/{tv_id}/approve", summary="Tasdiqlash (boshqa ekspert) — shartnoma turiga qo'llanadi")
async def approve_template(tv_id: uuid.UUID, db: DB, user: Approver) -> dict[str, Any]:
    tv = await service.get_version(db, tv_id)
    ctype = await service.approve(db, tv, user)
    return {"contract_type": ctype.code, "type_version": ctype.version, "template_version": tv.version}


@router.post("/{tv_id}/reject", response_model=TemplateOut)
async def reject_template(tv_id: uuid.UUID, body: RejectIn, db: DB, user: Approver) -> TemplateOut:
    tv = await service.get_version(db, tv_id)
    return TemplateOut.model_validate(await service.reject(db, tv, user, body.note))


@router.post("/check-sources", summary="lex.uz manbalarini hozir tekshirish (har kuni avtomatik ham)")
async def check_sources(db: DB, _: Editor) -> dict[str, Any]:
    return await service.check_sources(db)
