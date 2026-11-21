"""Negotiation, housekeeping and personal archive endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser, PageParams
from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.modules.contracts import archive, negotiation, service
from app.modules.contracts.router import ContractOut, contract_out

router = APIRouter(tags=["negotiation"])


class ObjectionIn(BaseModel):
    comment: str = Field(min_length=3, max_length=4000, description="Nimaga rozi emassiz va nima taklif qilasiz")
    fields: list[str] = Field(default_factory=list, description="Tegishli savolnoma maydonlari (kalitlar)")
    proposed: dict[str, Any] = Field(
        default_factory=dict, description="Taklif qilinayotgan qiymatlar {kalit: qiymat} — qabul qilinsa qo'llanadi"
    )


class ResolveIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RenameIn(BaseModel):
    title: str = Field(min_length=2, max_length=255)


class ArchivePatch(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


@router.get(
    "/contracts/{contract_id}/negotiation",
    summary="Kelishuv holati: kim nima qilishi kerak, rozilar, ochiq noroziliklar, maydon egalari, ogohlantirishlar",
)
async def get_state(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    return await negotiation.state(db, c, user, party)


@router.post(
    "/contracts/{contract_id}/agree",
    summary="Joriy shartlarga rozilik (ikkala tomon rozi bo'lsa umumiy shartnoma avtomatik yaratiladi)",
)
async def agree(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    return await negotiation.agree(db, c, user, party)


@router.get("/contracts/{contract_id}/objections", summary="Noroziliklar va qarshi takliflar")
async def objections(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    c, _ = await service.load_for(db, contract_id, user)
    return await negotiation.list_objections(db, c)


@router.post(
    "/contracts/{contract_id}/objections", status_code=201, summary="Norozilik bildirish / o'z taklifini yuborish"
)
async def object_to(contract_id: uuid.UUID, body: ObjectionIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    return await negotiation.object_to(
        db, c, user, party, comment=body.comment, fields=body.fields, proposed=body.proposed
    )


@router.post(
    "/contracts/{contract_id}/objections/{objection_id}/{action}",
    summary="Norozilikni qabul qilish (taklif qo'llanadi) / rad etish / qaytarib olish",
)
async def resolve(
    contract_id: uuid.UUID,
    objection_id: uuid.UUID,
    action: Literal["accept", "reject", "withdraw"],
    db: DB,
    user: CurrentUser,
    body: ResolveIn | None = None,
) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    return await negotiation.resolve_objection(
        db, c, user, party, objection_id, action=action, note=body.note if body else None
    )


@router.get("/contracts/{contract_id}/timeline", summary="Kelishuv tarixi (kim qachon nima qildi)")
async def timeline(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    c, _ = await service.load_for(db, contract_id, user)
    return await negotiation.timeline(db, c)


@router.delete(
    "/contracts/{contract_id}",
    summary="Qoralamani o'chirish (versiyasi bo'lsa — bekor qilinadi; imzolangan shartnoma o'chmaydi)",
)
async def delete_contract(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    return await negotiation.delete_or_cancel(db, c, user)


@router.patch("/contracts/{contract_id}", response_model=ContractOut, summary="Shartnoma nomini o'zgartirish")
async def rename(contract_id: uuid.UUID, body: RenameIn, db: DB, user: CurrentUser) -> ContractOut:
    c, _ = await service.load_for(db, contract_id, user)
    return contract_out(await negotiation.rename(db, c, user, body.title))


@router.delete(
    "/contracts/{contract_id}/parties/{party_id}/invitation",
    status_code=204,
    summary="Yuborilgan taklifni bekor qilish",
)
async def revoke_invitation(contract_id: uuid.UUID, party_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    c, _ = await service.load_for(db, contract_id, user)
    await negotiation.revoke_invitation(db, c, user, party_id)


@router.post(
    "/contracts/{contract_id}/duplicate",
    response_model=ContractOut,
    status_code=201,
    summary="Shu shartnoma asosida yangi qoralama (ikkinchi tomonning shaxsiy ma'lumotlarisiz)",
)
async def duplicate(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> ContractOut:
    c, party = await service.load_for(db, contract_id, user)
    return contract_out(await negotiation.duplicate(db, c, user, party))


# --- personal archive -------------------------------------------------------------------------------------


@router.get("/archive", summary="Mening arxivim: imzolangan shartnomalar")
async def list_archive(
    db: DB,
    user: CurrentUser,
    page: PageParams,
    q: str | None = Query(default=None, max_length=100),
    type_code: str | None = None,
) -> list[dict[str, Any]]:
    return await archive.list_items(db, user.id, q=q, type_code=type_code, limit=page.limit, offset=page.offset)


# documents (receipts, addenda) — registered before /archive/{item_id} so "documents" is not read as an id


@router.get("/archive/documents", summary="Arxivdagi to'lov cheklari va hujjatlar")
async def list_archive_documents(
    db: DB, user: CurrentUser, page: PageParams, archive_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    return await archive.list_documents(db, user.id, archive_id=archive_id, limit=page.limit, offset=page.offset)


@router.post(
    "/archive/documents",
    status_code=status.HTTP_201_CREATED,
    summary="Arxivga to'lov cheki yoki hujjat qo'shish (fayl ixtiyoriy: PDF, JPG/PNG, DOCX)",
)
async def add_archive_document(
    db: DB,
    user: CurrentUser,
    title: str = Form(..., max_length=255),
    kind: Literal["receipt", "addendum", "claim", "other"] = Form(default="receipt"),
    description: str | None = Form(default=None, max_length=4000),
    amount: str | None = Form(default=None, max_length=32),
    doc_date: date | None = Form(default=None),
    archive_id: uuid.UUID | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    value = None
    if amount and amount.strip():
        try:
            value = Decimal(amount.replace(" ", "").replace(",", "."))
        except InvalidOperation as e:
            raise ValidationFailed("Summa raqam bo'lishi kerak", code="doc_amount") from e
    upload = None
    if file is not None and file.filename:
        data = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
        upload = (data, file.filename, file.content_type)
    return await archive.add_document(
        db,
        user.id,
        title=title,
        kind=kind,
        description=description,
        amount=value,
        doc_date=doc_date,
        archive_id=archive_id,
        file=upload,
    )


@router.get("/archive/documents/{doc_id}/file", summary="Hujjat faylini yuklab olish")
async def download_archive_document(doc_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    data, f = await archive.document_file(db, user.id, doc_id)
    return Response(
        content=data,
        media_type=f.mime,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{f.original_name.encode("ascii", "replace").decode().replace("?", "_")}"; '
                f"filename*=UTF-8''{quote(f.original_name)}"
            ),
            "X-Content-SHA256": f.sha256,
        },
    )


@router.delete("/archive/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hujjatni o'chirish")
async def delete_archive_document(doc_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    await archive.delete_document(db, user.id, doc_id)


@router.get("/archive/{item_id}", summary="Arxivdagi shartnoma: imzolar, xesh yaxlitligi, yuklab olish")
async def get_archive_item(item_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await archive.get_item(db, user.id, item_id)


@router.patch("/archive/{item_id}", summary="Arxiv yozuviga shaxsiy izoh / teglar")
async def patch_archive_item(item_id: uuid.UUID, body: ArchivePatch, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await archive.update_item(db, user.id, item_id, note=body.note, tags=body.tags)
