"""Mediator application (O'RQ-482): draft, edit, AI help, DOCX download. Owner-only."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.core.ratelimit import get_limiter
from app.modules.mediation import service

router = APIRouter(prefix="/mediation", tags=["mediation"])


class MediationForm(BaseModel):
    applicant_name: str | None = Field(default=None, max_length=255, description="Arizachi F.I.Sh. / nomi")
    applicant_address: str | None = Field(default=None, max_length=500)
    applicant_phone: str | None = Field(default=None, max_length=32)
    respondent_name: str | None = Field(default=None, max_length=255, description="Ikkinchi tomon")
    respondent_address: str | None = Field(default=None, max_length=500)
    respondent_phone: str | None = Field(default=None, max_length=32)
    mediator_name: str | None = Field(default=None, max_length=255, description="Tanlangan mediator (ixtiyoriy)")
    mediator_org: str | None = Field(default=None, max_length=255, description="Mediatsiya tashkiloti (ixtiyoriy)")
    subject: str | None = Field(default=None, max_length=500, description="Nizo predmeti")
    description: str | None = Field(default=None, max_length=4000, description="Nizo mazmuni")
    claims: str | None = Field(default=None, max_length=4000, description="Talablar (har biri yangi qatorda)")
    desired_outcome: str | None = Field(default=None, max_length=2000, description="Murosa bo'yicha taklif")
    amount: str | None = Field(default=None, max_length=32, description="Nizo summasi (so'm)")
    city: str | None = Field(default=None, max_length=100)


class MediationCreate(MediationForm):
    contract_id: uuid.UUID | None = Field(
        default=None, description="Nizo kelib chiqqan shartnoma — tomonlar va predmet avtomatik to'ldiriladi"
    )


@router.get("/requests", summary="Mening mediatorga arizalarim")
async def list_requests(db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    return await service.list_for(db, user)


@router.post("/requests", status_code=status.HTTP_201_CREATED, summary="Mediatorga ariza (qoralama) yaratish")
async def create_request(body: MediationCreate, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await service.create(db, user, body.model_dump(exclude={"contract_id"}, exclude_none=True), body.contract_id)


@router.get("/requests/{request_id}", summary="Ariza")
async def get_request(request_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await service.get(db, user, request_id)


@router.patch("/requests/{request_id}", summary="Arizani tahrirlash (null yoki bo'sh qiymat maydonni tozalaydi)")
async def update_request(request_id: uuid.UUID, body: MediationForm, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await service.update(db, user, request_id, body.model_dump(exclude_unset=True))


@router.delete("/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Arizani o'chirish")
async def delete_request(request_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    await service.delete(db, user, request_id)


@router.post(
    "/requests/{request_id}/ai",
    summary="AI yordam: xolis nizo matni, talablar, murosa variantlari (lex.uz moddalariga tayanadi)",
)
async def ai_help(request_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    await get_limiter().hit(f"ai:{user.id}", limit=40, window_s=3600)
    return await service.ai_help(db, user, request_id)


@router.get(
    "/requests/{request_id}/docx", summary="Arizani DOCX yuklab olish (+ mediatsiyani qo'llash kelishuvi loyihasi)"
)
async def download_docx(request_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    data, filename = await service.build_docx(db, user, request_id)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename.encode("ascii", "replace").decode().replace("?", "_")}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )
