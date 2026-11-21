"""Endpoints the web app needs on top of the domain modules (one call per screen widget)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.core.ratelimit import get_limiter
from app.modules.assistant import chat as chat_service
from app.modules.assistant import service

router = APIRouter(tags=["assistant"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(
        min_length=1, max_length=20, description="Suhbat (eng oxirgisi — foydalanuvchi savoli); server saqlamaydi"
    )
    contract_id: uuid.UUID | None = Field(default=None, description="Ochiq shartnoma — AI shu shartnomaga tayanadi")
    page: str | None = Field(default=None, max_length=40, description="Foydalanuvchi turgan sahifa (dashboard, ...)")


@router.post(
    "/assistant/chat",
    summary="«Shartnomachi AI»: shartnomalar, nizolar va qonunlar bo'yicha savol-javob (lex.uz moddalariga tayanadi)",
)
async def chat(body: ChatIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    await get_limiter().hit(f"ai:{user.id}", limit=60, window_s=3600)
    return await chat_service.chat(
        db,
        user,
        [m.model_dump() for m in body.messages],
        contract_id=body.contract_id,
        page=body.page,
    )


class SituationIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000, description="Foydalanuvchi o'z vaziyatini erkin yozadi")


@router.post(
    "/assistant/situation",
    summary="«Vaziyatingizni yozing»: mos shartnoma turi va keyingi qadam (qoidalar + AI)",
)
async def situation(body: SituationIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    await get_limiter().hit(f"ai:{user.id}", limit=40, window_s=3600)
    return await service.situation(db, user, body.text)


@router.get("/dashboard", summary="Bosh sahifa uchun hammasi bitta so'rovda")
async def dashboard(db: DB, user: CurrentUser) -> dict[str, Any]:
    return await service.dashboard(db, user)


@router.get("/lookup/stir/{stir}", summary="STIR bo'yicha tashkilot ma'lumotlari (platformada ro'yxatdagilar)")
async def lookup_stir(stir: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    await get_limiter().hit(f"stir:{user.id}", limit=60, window_s=3600)
    return await service.lookup_stir(db, stir)
