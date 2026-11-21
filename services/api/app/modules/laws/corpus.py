"""Law corpus from lex.uz: codes split into articles, stored in packages/legal-content/laws/<code>.json.

Rules and contract templates cite articles by (code, number); the AI review is given the *text* of the
articles relevant to the contract type, so it judges against the law as published on lex.uz, not from memory.

    python -m app.modules.laws.cli sync            # (re)import every source listed in SOURCES
    python -m app.modules.laws.cli check           # report sources whose lex.uz edition changed
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.errors import NotFound
from app.integrations import lexuz

# code -> lex.uz document (negative id = Uzbek, Latin script)
SOURCES: dict[str, dict[str, str]] = {
    "fk1": {
        "doc_id": "-111189",
        "short": "FK",
        "title": "O‘zbekiston Respublikasining Fuqarolik kodeksi (birinchi qism)",
    },
    "fk2": {
        "doc_id": "-180552",
        "short": "FK",
        "title": "O‘zbekiston Respublikasining Fuqarolik kodeksi (ikkinchi qism)",
    },
    "mk": {"doc_id": "-6257288", "short": "MK", "title": "O‘zbekiston Respublikasining Mehnat kodeksi"},
    "consumer": {
        "doc_id": "-4704",
        "short": "IHHQ",
        "title": "«Iste’molchilarning huquqlarini himoya qilish to‘g‘risida»gi Qonun",
    },
    "mediation": {"doc_id": "-3805227", "short": "MQ", "title": "«Mediatsiya to‘g‘risida»gi Qonun (O‘RQ-482)"},
}

_ART = re.compile(r"^(\d{1,4})(?:[\.‐\-–]?\d{0,2})?-modda\.?\s*(.*)$", re.IGNORECASE)
_CHAPTER_KINDS = {"TEXT_HEADER_DEFAULT"}
_NOTE_KINDS = {"BY_DEFAULT"}  # editorial notes «(... tahririda)» — kept apart from the article text


@dataclass(slots=True)
class Article:
    number: str
    title: str
    chapter: str | None
    text: str
    anchor: str | None
    notes: list[str] = field(default_factory=list)


def _content_dir() -> Path:
    from app.seed import content_dir

    return content_dir() / "laws"


def split_articles(doc: lexuz.LexDocument) -> list[Article]:
    out: list[Article] = []
    chapter: str | None = None
    cur: Article | None = None
    for b in doc.blocks:
        first = (b.lines[0] if b.lines else "").strip()
        if b.kind in _CHAPTER_KINDS:
            chapter = " ".join(line.strip() for line in b.lines if line.strip())[:200] or chapter
            continue
        m = _ART.match(first) if b.kind == "CLAUSE_DEFAULT" else None
        if m:
            cur = Article(number=m.group(1), title=m.group(2).strip(), chapter=chapter, text="", anchor=b.element_id)
            out.append(cur)
            continue
        if cur is None:
            continue
        if b.kind in _NOTE_KINDS:
            cur.notes.append(b.text.strip())
        elif b.kind not in ("CLAUSE_DEFAULT",):
            cur.text = (cur.text + "\n" + b.text).strip()
    return out


async def import_source(code: str) -> dict[str, Any]:
    src = SOURCES[code]
    doc = await lexuz.fetch(src["doc_id"], lang="uz")
    arts = split_articles(doc)
    data = {
        "code": code,
        "doc_id": src["doc_id"],
        "short": src["short"],
        "title": doc.title,
        "url": doc.url,
        "edition_date": doc.edition_date.isoformat() if doc.edition_date else None,
        "lost_force": doc.lost_force,
        "content_sha256": doc.content_hash(),
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "articles": [asdict(a) for a in arts],
    }
    path = _content_dir() / f"{code}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    load.cache_clear()
    return {"code": code, "articles": len(arts), "edition_date": data["edition_date"], "path": str(path)}


@lru_cache
def load(code: str) -> dict[str, Any]:
    path = _content_dir() / f"{code}.json"
    if not path.is_file():
        raise NotFound(f"Law corpus '{code}' is not imported", code="law_not_imported")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_by_number"] = {a["number"]: a for a in data["articles"]}
    return data


def available() -> list[str]:
    d = _content_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def article_url(code: str, anchor: str | None) -> str:
    base = load(code)["url"]
    return f"{base}#{anchor}" if anchor else base


def article(code: str, number: int | str) -> dict[str, Any]:
    data = load(code)
    a = data["_by_number"].get(str(number))
    if a is None:
        raise NotFound(f"Article {number} not found in {code}", code="article_not_found")
    return {
        "code": code,
        "law": data["title"],
        "short": data["short"],
        "number": a["number"],
        "title": a["title"],
        "chapter": a["chapter"],
        "text": a["text"],
        "url": article_url(code, a["anchor"]),
        "edition_date": data["edition_date"],
    }


def cite(code: str, number: int | str) -> str:
    """«FK 326-modda. Neustoykani kamaytirish» — the human citation used in findings."""
    a = article(code, number)
    return f"{a['short']} {a['number']}-modda. {a['title']}".strip()


def search(query: str, *, codes: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
    hits: list[tuple[int, dict[str, Any]]] = []
    for code in codes or available():
        data = load(code)
        for a in data["articles"]:
            hay_title = a["title"].lower()
            hay = hay_title + " " + a["text"].lower()
            score = sum(3 * hay_title.count(w) + hay.count(w) for w in words)
            if query.lower().strip() in hay_title:
                score += 100  # the whole phrase is the article title
            elif all(w in hay_title for w in words):
                score += 20
            if score and all(w in hay for w in words):
                hits.append(
                    (score, {"code": code, "number": a["number"], "title": a["title"], "chapter": a["chapter"]})
                )
    hits.sort(key=lambda x: -x[0])
    return [h for _, h in hits[:limit]]


def articles_for(legal_refs: list[dict[str, Any]] | None, *, max_chars: int = 900) -> list[dict[str, Any]]:
    """Articles referenced by a contract type (`legal_refs[].code/number`), text trimmed for prompts."""
    out = []
    for ref in legal_refs or []:
        code, number = ref.get("code"), ref.get("number")
        if not code or not number:
            continue
        try:
            a = article(code, number)
        except NotFound:
            continue
        text = a["text"]
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + " …"
        out.append({**a, "text": text})
    return out


def prompt_block(arts: list[dict[str, Any]]) -> list[str]:
    return [f"[{a['short']} {a['number']}-modda. {a['title']}] {a['text']}" for a in arts]


# words that say nothing about *which* article a question is about
_QSTOP = {
    "qancha", "qanday", "qachon", "qaysi", "nima", "nimaga", "nega", "uchun", "bilan", "bo'lsa", "bo'yicha",
    "qonun", "qonunga", "qonunda", "shartnoma", "shartnomada", "shartnomasi", "shartnomani", "mumkin",
    "kerak", "bormi", "yo'qmi", "emas", "yoki", "agar", "menga", "mening", "meni", "bizning", "ushbu", "kodeks",
    "kodeksi", "modda", "moddasi", "bo'ladi", "bo'lishi", "qilish", "qiladi", "qilsa", "beradi", "olish", "kim",
    "hamda", "lekin", "ammo", "bunda", "boshqa", "tomon", "tomonidan", "tomonlar",
}


def _norm_q(text: str) -> str:
    return re.sub(r"[ʻʼ’‘`]", "'", (text or "").lower())


@lru_cache(maxsize=16)
def _index(code: str) -> tuple[tuple[str, str, str], ...]:
    return tuple((a["number"], _norm_q(a["title"]), _norm_q(a["text"])) for a in load(code)["articles"])


def related(
    question: str, *, codes: list[str] | None = None, limit: int = 4, max_chars: int = 900
) -> list[dict[str, Any]]:
    """Articles most relevant to a free-text question (word stems, title weighted) — for AI answers."""
    words = [w for w in re.split(r"[^\w']+", _norm_q(question)) if len(w) >= 4 and w not in _QSTOP]
    stems = list(dict.fromkeys(w[:5] if len(w) >= 7 else w[:4] for w in words))
    if not stems:
        return []
    need = min(2, len(stems))
    hits: list[tuple[int, str, str]] = []
    for code in [c for c in (codes or available()) if c in available()]:
        for number, title, text in _index(code):
            matched = [s for s in stems if s in title or s in text]
            if len(matched) < need:
                continue
            score = 10 * len(matched) + sum(4 * title.count(s) + min(text.count(s), 5) for s in matched)
            hits.append((score, code, number))
    hits.sort(key=lambda h: -h[0])
    out = []
    for _, code, number in hits[:limit]:
        a = article(code, number)
        if len(a["text"]) > max_chars:
            a["text"] = a["text"][:max_chars].rsplit(" ", 1)[0] + " …"
        out.append(a)
    return out


_REF = re.compile(r"\b(FK|MK|IHHQ|MQ)\s*(\d{1,4})", re.IGNORECASE)


def resolve(ref_text: str) -> list[dict[str, Any]]:
    """«FK 237-modda …; FK 382-modda …» -> the articles (Civil Code parts are numbered continuously)."""
    out: list[dict[str, Any]] = []
    for short, number in _REF.findall(ref_text or ""):
        codes = [c for c, src in SOURCES.items() if src["short"].lower() == short.lower() and c in available()]
        for code in codes:
            try:
                out.append(article(code, number))
                break
            except NotFound:
                continue
    return out
