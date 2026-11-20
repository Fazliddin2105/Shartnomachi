"""Law texts from lex.uz (read-only): sources, single article, search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.modules.laws import corpus

router = APIRouter(prefix="/laws", tags=["laws"])


@router.get("", summary="Import qilingan qonunlar (lex.uz): nomi, tahrir sanasi, havola")
async def sources() -> list[dict[str, Any]]:
    out = []
    for code in corpus.available():
        d = corpus.load(code)
        out.append(
            {
                "code": code,
                "short": d["short"],
                "title": d["title"],
                "url": d["url"],
                "edition_date": d["edition_date"],
                "fetched_at": d["fetched_at"],
                "articles": len(d["articles"]),
            }
        )
    return out


@router.get("/search", summary="Moddalar bo'yicha qidiruv (sarlavha va matn)")
async def search(
    q: str = Query(min_length=3, max_length=200), code: list[str] | None = Query(default=None), limit: int = 20
) -> list[dict[str, Any]]:
    return corpus.search(q, codes=code, limit=min(max(limit, 1), 50))


@router.get("/resolve", summary="Havola matnidan («FK 615-modda …») moddalar matnini olish")
async def resolve(ref: str = Query(min_length=3, max_length=300)) -> list[dict[str, Any]]:
    return corpus.resolve(ref)


@router.get("/{code}/articles/{number}", summary="Modda matni (lex.uz'dagi aniq havolasi bilan)")
async def article(code: str, number: str) -> dict[str, Any]:
    return corpus.article(code, number)
