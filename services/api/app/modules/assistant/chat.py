"""«Shartnomachi AI» — the site-wide chat assistant.

Stateless: the browser sends the recent conversation each time (nothing is stored server-side). Answers are
grounded in lex.uz article texts (picked for the question, or for the user's contract when one is open) and
may cite only those articles; the suggested next step is validated against the platform's sections.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import llm, prompts
from app.ai import service as ai
from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.modules.assistant.service import _types
from app.modules.contracts import service as contracts
from app.modules.laws import corpus
from app.modules.users.models import User

ACTIONS = {
    "builder": "Shartnoma tuzish",
    "scanner": "Shartnomani tekshirish",
    "mediation": "Mediatorga ariza tayyorlash",
    "contracts": "Shartnomalarim",
    "archive": "Arxiv",
    "reminders": "To'lov eslatmalari",
}
MAX_HISTORY = 8
_MEDIATION_HINT = re.compile(r"nizo|mediat|kelishmov|janjal|sudga|da'vo|даъво|спор|медиац", re.I)
MEDIATION_CORE = ("15", "16", "21", "23", "28", "29", "291")


def _trim(a: dict[str, Any], max_chars: int = 700) -> dict[str, Any]:
    text = a["text"]
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    return {**a, "text": text}


def law_texts_for(question: str, ctype: Any | None) -> list[str] | None:
    """Articles of the open contract's type + those matching the question (+ the mediation basics for disputes)."""
    arts: list[dict[str, Any]] = []
    if ctype is not None:
        arts = corpus.articles_for(ctype.legal_refs, max_chars=600)
    seen = {(a["code"], str(a["number"])) for a in arts}

    def add(a: dict[str, Any]) -> None:
        if (a["code"], str(a["number"])) not in seen:
            seen.add((a["code"], str(a["number"])))
            arts.append(_trim(a))

    if _MEDIATION_HINT.search(question) and "mediation" in corpus.available():
        for n in MEDIATION_CORE:
            add(corpus.article("mediation", n))
    for a in corpus.related(question, limit=5, max_chars=700):
        add(a)
    return corpus.prompt_block(arts[:22]) or None


async def chat(
    db: AsyncSession,
    user: User,
    messages: list[dict[str, str]],
    *,
    contract_id: uuid.UUID | None = None,
    page: str | None = None,
) -> dict[str, Any]:
    if not messages or messages[-1]["role"] != "user":
        raise ValidationFailed("The last message must be the user's question", code="chat_no_question")
    question = messages[-1]["content"].strip()
    history = [m for m in messages[:-1] if m["content"].strip()][-MAX_HISTORY:]

    contract_text, ctype = None, None
    if contract_id is not None:
        c, _ = await contracts.load_for(db, contract_id, user)  # 404/403 if not the user's contract
        ctype = c.contract_type
        clauses = await contracts._clauses_for_ai(db, c)
        contract_text = f"«{c.title}» ({ctype.title_uz if ctype else 'shartnoma'})\n" + prompts.clauses_block(
            clauses, 8000
        )

    types = await _types(db)
    by_code = {t.code: t for t in types}
    catalog = "\n".join(f"- {t.code}: {t.title_uz}" for t in types)
    # previous user turn helps short follow-ups («qancha muddatga?») find the right articles
    prev_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    law_texts = law_texts_for(f"{question} {prev_user}".strip(), ctype)

    ans = await llm.ask_json(
        prompts.CHAT_SYSTEM,
        prompts.chat_user(
            history=history, question=question, catalog=catalog, law_texts=law_texts, contract=contract_text, page=page
        ),
        max_tokens=900,
    )
    d = ans.data
    answer = ai._s(d.get("answer"), 3000) or "Kechirasiz, javob tayyorlay olmadim. Savolni boshqacha yozib ko'ring."
    conf = ai._f(d.get("confidence"))

    action = None
    raw = d.get("action")
    if isinstance(raw, dict) and raw.get("type") in ACTIONS:
        code = raw.get("type_code") if raw.get("type_code") in by_code else None
        if raw["type"] != "builder" or code:
            label = ACTIONS[raw["type"]] + (f": {by_code[code].title_uz}" if code else "")
            action = {"type": raw["type"], "type_code": code, "label": label}

    return {
        "answer": answer,
        "law_refs": ai._law_refs(d.get("law_refs"), answer, law_texts),
        "action": action,
        "consult_lawyer": conf < get_settings().llm_min_confidence,
        "model": ans.model,
        "masked": ans.masked,
        "disclaimer": "Shartnomachi AI huquqiy axborot beradi va yurist maslahatini almashtirmaydi.",
    }
