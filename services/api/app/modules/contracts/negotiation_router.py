"""Negotiation, housekeeping and personal archive endpoints."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser, PageParams
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


@router.get("/archive/{item_id}", summary="Arxivdagi shartnoma: imzolar, xesh yaxlitligi, yuklab olish")
async def get_archive_item(item_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await archive.get_item(db, user.id, item_id)


@router.patch("/archive/{item_id}", summary="Arxiv yozuviga shaxsiy izoh / teglar")
async def patch_archive_item(item_id: uuid.UUID, body: ArchivePatch, db: DB, user: CurrentUser) -> dict[str, Any]:
    return await archive.update_item(db, user.id, item_id, note=body.note, tags=body.tags)
