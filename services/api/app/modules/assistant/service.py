"""Workspace helpers for the web app: situation assistant, dashboard aggregate, STIR lookup."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import llm, prompts
from app.core.errors import AppError
from app.modules.contracts import service as contracts
from app.modules.contracts.models import ContractStatus, ContractType
from app.modules.notifications.models import Notification
from app.modules.obligations import service as obligations
from app.modules.scan import service as scans
from app.modules.scan.models import ScanJob, ScanStatus
from app.modules.users.models import Company, User

log = logging.getLogger(__name__)

# «check / analyse / I was given a contract» -> scanner; otherwise the user wants to draft one
_SCAN_INTENT = re.compile(
    r"tekshir|tahlil|xavf|skaner|imzola(sh|y)dan oldin|berishdi|yubor(ish)?di|olib keldi|"
    r"qaltis|ishonchli|aldan|провер|анализ|риск|подпис",
    re.I,
)


async def _types(db: AsyncSession) -> list[ContractType]:
    return list(await db.scalars(select(ContractType).where(ContractType.is_active.is_(True))))


def _rules_guess(text: str, types: list[ContractType]) -> tuple[str | None, list[str]]:
    """Keyword scoring tuned for short free text (one hit is enough), distinctive words first."""
    t = text.lower()
    lists = [(ct.code, {k.lower() for k in (ct.detect_keywords or []) if k}) for ct in types]
    df: dict[str, int] = {}
    for _, kws in lists:
        for k in kws:
            df[k] = df.get(k, 0) + 1
    # stems so «ijaraga bermoqchiman», «qarzga», «ishga olaman» also match
    stems = {
        "ijara": ["rent_residential", "rent_private", "rent_commercial"],
        "kvartira": ["rent_residential"],
        "uy ": ["rent_residential"],
        "noturar": ["rent_commercial"],
        "ofis": ["rent_commercial"],
        "do'kon": ["rent_commercial"],
        "do‘kon": ["rent_commercial"],
        "qarz": ["loan", "loan_notarial"],
        "notarius": ["loan_notarial"],
        "ishga ol": ["labor"],
        "xodim": ["labor"],
        "mehnat": ["labor"],
        "sotib ol": ["sale"],
        "sotmoqchi": ["sale"],
        "sotaman": ["sale"],
        "mashina": ["sale"],
        "xizmat": ["services"],
        "ta'mir": ["services"],
        "dastur": ["services"],
    }
    scores: dict[str, float] = {}
    for code, kws in lists:
        scores[code] = sum(1 / df[k] for k in kws if k in t)
    for stem, codes in stems.items():
        if stem in t:
            for code in codes:
                if code in scores:
                    scores[code] += 0.5 / len(codes)
    ranked = sorted((c for c, s in scores.items() if s > 0), key=lambda c: -scores[c])
    return (ranked[0] if ranked else None), ranked[1:3]


async def situation(db: AsyncSession, user: User, text: str) -> dict[str, Any]:
    types = await _types(db)
    by_code = {t.code: t for t in types}
    code, alternatives = _rules_guess(text, types)
    action = "scanner" if _SCAN_INTENT.search(text) else ("builder" if code else "consult")
    answer: str | None = None
    steps: list[str] = []
    source, model = "rules", None
    if llm.is_enabled():
        catalog = "\n".join(f"- {t.code}: {t.title_uz} — {t.description or ''}" for t in types)
        try:
            ans = await llm.ask_json(
                prompts.SITUATION_SYSTEM,
                prompts.situation_user(text=text, catalog=catalog),
                max_tokens=700,
            )
            d = ans.data
            if d.get("type_code") in by_code or d.get("type_code") is None:
                code = d.get("type_code") or code
            if d.get("action") in ("builder", "scanner", "consult"):
                action = d["action"]
            answer = str(d.get("answer") or "")[:1500] or None
            if answer:  # a reply without an answer is not used (rules result stands)
                steps = [str(s)[:300] for s in (d.get("steps") or [])][:6]
                ai_alts = [c for c in (d.get("alternatives") or []) if c in by_code and c != code]
                alternatives = ai_alts[:2] or alternatives
                source, model = "ai", ans.model
        except AppError as e:  # AI is a helper: the rules answer still goes out
            log.warning("situation_ai_failed", extra={"error": e.code})
    if answer is None:
        if code:
            verb = "tekshirib beramiz" if action == "scanner" else "savolnoma asosida tuzib beramiz"
            answer = f"Vaziyatingizga «{by_code[code].title_uz}» mos keladi — {verb}."
        else:
            answer = "Vaziyatni aniqlay olmadik. Shartnoma turini tanlang yoki tayyor shartnomani yuklab tekshiring."

    def brief(c: str | None) -> dict[str, Any] | None:
        t = by_code.get(c or "")
        return None if t is None else {"code": t.code, "title": t.title_uz, "source": (t.source or {}).get("kind")}

    return {
        "action": action,
        "contract_type": brief(code),
        "alternatives": [b for b in (brief(c) for c in alternatives) if b],
        "answer": answer,
        "steps": steps,
        "source": source,
        "model": model,
        "disclaimer": "Platforma huquqiy axborot beradi va malakali yurist maslahatini almashtirmaydi.",
    }


async def dashboard(db: AsyncSession, user: User) -> dict[str, Any]:
    from app.modules.contracts.router import contract_out
    from app.modules.obligations.router import ObligationOut

    all_contracts = await contracts.list_for(db, user, None, 200, 0)
    counts = {s.value: 0 for s in ContractStatus}
    for c in all_contracts:
        counts[c.status.value] += 1

    ob = await obligations.dashboard(db, user)
    last = await db.scalar(
        select(ScanJob)
        .where(ScanJob.owner_id == user.id, ScanJob.status == ScanStatus.DONE)
        .order_by(ScanJob.created_at.desc())
        .limit(1)
    )
    last_scan = None
    if last is not None:
        rep = await scans.report(db, last)
        o = rep["overall"]
        top = (rep["red_clauses"] + rep["risky_clauses"] + rep["missing_elements"])[:3]
        last_scan = {
            "id": str(last.id),
            "created_at": last.created_at.isoformat(),
            "title": (rep.get("document") or {}).get("title"),
            "contract_type_code": last.contract_type_code,
            "risk_level": o.get("risk_level"),
            "risk_percent": o.get("risk_percent"),
            "risk_label": o.get("risk_label"),
            "counts": {"red": o.get("red", 0), "yellow": o.get("yellow", 0), "missing": o.get("missing", 0)},
            "template_conformity": (o.get("template_check") or {}).get("conformity"),
            "ai_status": rep.get("ai", {}).get("status"),
            "top_findings": [
                {
                    "id": f["id"],
                    "severity": f["severity"],
                    "explanation": f["ai_explanation"] or f["explanation"],
                    "law_ref": f["law_ref"],
                    "clause_text": f["clause_text"],
                    "suggestion": f["suggestion"],
                    "user_decision": f["user_decision"],
                }
                for f in top
            ],
        }
    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    profile = user.profile
    return {
        "user": {
            "id": str(user.id),
            "name": (profile.full_name if profile else None) or None,
            "phone_masked": f"{user.phone[:6]}***{user.phone[-2:]}" if user.phone else None,
            "role": user.role.value,
            "identity_verified": user.identity_verified_via is not None,
        },
        "contracts": {
            "recent": [contract_out(c).model_dump(mode="json") for c in all_contracts[:5]],
            "counts": counts,
            "total": len(all_contracts),
        },
        "invitations": len(await contracts.list_invitations(db, user)),
        "obligations": {
            "upcoming_30d": [ObligationOut.model_validate(o).model_dump(mode="json") for o in ob.upcoming_30d],
            "overdue": [ObligationOut.model_validate(o).model_dump(mode="json") for o in ob.overdue],
            "unpaid_total": ob.unpaid_total,
            "unconfirmed": ob.unconfirmed,
            "risk": ob.risk,
        },
        "last_scan": last_scan,
        "notifications_unread": unread or 0,
        "ai": {"enabled": llm.is_enabled()},
    }


_STIR = re.compile(r"^\d{9}$")


async def lookup_stir(db: AsyncSession, stir: str) -> dict[str, Any]:
    stir = stir.strip()
    if not _STIR.fullmatch(stir):
        return {"stir": stir, "valid": False, "found": False, "message": "STIR 9 ta raqamdan iborat bo'lishi kerak."}
    company = await db.scalar(select(Company).where(Company.stir == stir))
    if company is None:
        return {
            "stir": stir,
            "valid": True,
            "found": False,
            "source": None,
            "message": "Bu STIR platformada ro'yxatdan o'tmagan (soliq.uz integratsiyasi hali ulanmagan) — "
            "ma'lumotlarni qo'lda kiriting.",
        }
    req = company.requisites or {}
    return {
        "stir": stir,
        "valid": True,
        "found": True,
        "source": "platform",
        "name": f"{company.name}",
        "legal_form": company.legal_form,
        "address": company.address,
        "director": company.director_name,
        # public business details used in contract requisites (no personal data)
        "mfo": req.get("mfo"),
        "oked": req.get("oked"),
        "bank": req.get("bank"),
    }
