"""AI analysis on top of the deterministic engine.

Policy (spec §9, "qoida ustun"):
  * AI never blocks: an AI "red" is shown as «AI: ehtimoliy qonunbuzarlik — yurist tekshirsin» (yellow);
  * AI issues on a clause the rule engine already flagged are dropped (no duplicates, rules win);
  * confidence below `llm_min_confidence` => needs_lawyer;
  * extracted obligations are suggestions until the user confirms them.
The template comparison is deterministic (difflib) and works without any model.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.ai import llm, prompts
from app.core.config import get_settings
from app.core.timeutils import today_local
from app.core.translit import cyr_to_lat

_SEVERITIES = {"red", "yellow", "blue"}


@dataclass(slots=True)
class AIIssue:
    clause_index: int | None
    severity: str  # displayed severity after policy (yellow|blue)
    ai_severity: str  # what the model said
    title: str
    explanation: str
    law_ref: str | None
    suggestion: str | None
    confidence: float

    @property
    def needs_lawyer(self) -> bool:
        return self.confidence < get_settings().llm_min_confidence or self.ai_severity == "red"


@dataclass(slots=True)
class AIReview:
    summary: str
    risk_level: str
    issues: list[AIIssue] = field(default_factory=list)
    obligations: list[dict[str, Any]] = field(default_factory=list)
    template_deviations: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    masked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "risk_level": self.risk_level,
            "issues": [{**asdict(i), "needs_lawyer": i.needs_lawyer} for i in self.issues],
            "obligations": self.obligations,
            "template_deviations": self.template_deviations,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "masked": self.masked,
            "prompt_version": prompts.PROMPT_VERSION,
        }


def _f(v: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def _s(v: Any, limit: int = 1200) -> str | None:
    if v is None:
        return None
    t = str(v).strip()
    return t[:limit] or None


def normalise(data: dict[str, Any], *, n_clauses: int, flagged: set[int]) -> AIReview:
    issues: list[AIIssue] = []
    for raw in data.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        sev = str(raw.get("severity", "blue")).lower()
        sev = sev if sev in _SEVERITIES else "blue"
        idx = raw.get("clause_index")
        idx = idx if isinstance(idx, int) and 0 <= idx < n_clauses else None
        if idx is not None and idx in flagged:
            continue  # the rule engine already covers this clause — rules win
        title, expl = _s(raw.get("title"), 200), _s(raw.get("explanation"))
        if not (title or expl):
            continue
        issues.append(
            AIIssue(
                clause_index=idx,
                severity="yellow" if sev == "red" else sev,
                ai_severity=sev,
                title=title or "AI ogohlantirishi",
                explanation=expl or "",
                law_ref=_s(raw.get("law_ref"), 255),
                suggestion=_s(raw.get("suggestion")),
                confidence=_f(raw.get("confidence")),
            )
        )
    obligations = []
    for raw in data.get("obligations") or []:
        if not isinstance(raw, dict) or not _s(raw.get("title")):
            continue
        due = raw.get("due_date")
        due = due if isinstance(due, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due) else None
        amount = raw.get("amount")
        amount = amount if isinstance(amount, (int, float)) and amount >= 0 else None
        obligations.append(
            {
                "party": raw.get("party") if raw.get("party") in ("A", "B") else "unknown",
                "who": _s(raw.get("who"), 120),
                "title": _s(raw.get("title"), 255),
                "due_date": due,
                "amount": amount,
                "currency": raw.get("currency") if raw.get("currency") in ("UZS", "USD") else None,
                "recurring": "monthly" if raw.get("recurring") == "monthly" else None,
                "clause_index": raw.get("clause_index") if isinstance(raw.get("clause_index"), int) else None,
                "confidence": _f(raw.get("confidence")),
            }
        )
    deviations = [
        {
            "template_clause": _s(d.get("template_clause"), 300),
            "status": d.get("status"),
            "comment": _s(d.get("comment"), 600),
        }
        for d in data.get("template_deviations") or []
        if isinstance(d, dict) and d.get("status") in ("missing", "changed")
    ]
    risk = str(data.get("risk_level", "")).lower()
    return AIReview(
        summary=_s(data.get("summary"), 1500) or "",
        risk_level=risk if risk in ("low", "medium", "high") else "medium",
        issues=issues,
        obligations=obligations,
        template_deviations=deviations,
    )


async def review(
    *,
    clauses: list[dict[str, Any]],
    contract_type: str | None,
    rule_findings: list[dict[str, Any]],
    template_clauses: list[str] | None,
    template_label: str | None = None,
    law_texts: list[str] | None = None,
) -> AIReview:
    flagged = {f["clause_index"] for f in rule_findings if isinstance(f.get("clause_index"), int)}
    user = prompts.review_user(
        contract_type=contract_type,
        clauses=clauses,
        rule_findings=[f"[{f.get('clause_index')}] {f.get('message')}" for f in rule_findings],
        template_clauses=template_clauses,
        template_label=template_label,
        law_texts=law_texts,
        today=today_local().isoformat(),
    )
    ans = await llm.ask_json(prompts.REVIEW_SYSTEM, user)
    out = normalise(ans.data, n_clauses=len(clauses), flagged=flagged)
    out.model, out.latency_ms, out.masked = ans.model, ans.latency_ms, ans.masked
    return out


async def ask(*, clauses: list[dict[str, Any]], findings: list[str], question: str) -> dict[str, Any]:
    ans = await llm.ask_json(
        prompts.ASK_SYSTEM, prompts.ask_user(clauses=clauses, findings=findings, question=question), max_tokens=900
    )
    d = ans.data
    conf = _f(d.get("confidence"))
    refs = [r for r in (d.get("clause_refs") or []) if isinstance(r, int) and 0 <= r < len(clauses)]
    return {
        "answer": _s(d.get("answer"), 4000) or "Javob olinmadi.",
        "clause_refs": refs,
        "confidence": conf,
        "consult_lawyer": bool(d.get("consult_lawyer")) or conf < get_settings().llm_min_confidence,
        "model": ans.model,
        "masked": ans.masked,
        "disclaimer": "AI javobi ma'lumot uchun; yuridik maslahat o'rnini bosmaydi.",
    }


# --- deterministic comparison with the official (lex.uz) template --------------------------------

_PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)


def _norm(text: str) -> str:
    t = cyr_to_lat(text).lower().replace("ʻ", "'").replace("’", "'")
    t = re.sub(r"_+", " ", _PLACEHOLDER.sub(" ", t))
    t = re.sub(r"^\s*\d{1,2}\.\s*", "", t)
    return re.sub(r"[^\w' ]+", " ", re.sub(r"\s+", " ", t)).strip()


def compare_with_template(
    clause_texts: list[str], template: dict[str, Any], *, granular: bool = False
) -> dict[str, Any]:
    """For every clause of the reference form: matched / changed / missing in the uploaded contract.

    ``granular`` is for references split into numbered sub-clauses (organization templates): the
    upload is compared line by line and word coverage is weighted by how distinctive a word is
    within the reference (a sub-clause is «present» only if its own key words are there).
    """
    if granular:
        return _compare_granular(clause_texts, template)
    uploaded = [_norm(t) for t in clause_texts]
    # an official clause may be split over neighbouring clauses of the uploaded text: windows of 1..3
    windows = [" ".join(uploaded[i : i + n]) for n in (1, 2, 3) for i in range(len(uploaded) - n + 1)]
    results = []
    for c in template.get("clauses", []):
        if c.get("key") in ("requisites", "notes"):
            continue
        ref = _norm(c.get("body", ""))
        if len(ref) < 25:
            continue
        ref_words = {w for w in ref.split() if len(w) > 3}
        best = 0.0
        for w in windows:
            ratio = difflib.SequenceMatcher(None, ref, w, autojunk=False).ratio()
            coverage = len(ref_words & set(w.split())) / max(len(ref_words), 1)
            best = max(best, 0.5 * ratio + 0.5 * coverage)  # wording similarity + content coverage
        score = best
        status = "ok" if score >= 0.65 else ("changed" if score >= 0.4 else "missing")
        results.append(
            {
                "key": c.get("key"),
                "title": (c.get("body", "").split("\n")[0])[:120],
                "score": round(score, 2),
                "status": status,
            }
        )
    total = len(results) or 1
    return {
        "clauses": results,
        "matched": sum(r["status"] == "ok" for r in results),
        "changed": [r for r in results if r["status"] == "changed"],
        "missing": [r for r in results if r["status"] == "missing"],
        "conformity": round(sum(r["status"] == "ok" for r in results) / total, 2),
    }


def _compare_granular(clause_texts: list[str], template: dict[str, Any]) -> dict[str, Any]:
    import math

    lines = [_norm(ln) for t in clause_texts for ln in t.splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln]
    windows = [" ".join(lines[i : i + n]) for n in (1, 2) for i in range(len(lines) - n + 1)]
    window_words = [set(w.split()) for w in windows]
    refs = []
    for c in template.get("clauses", []):
        ref = _norm(c.get("body", ""))
        if len(ref) >= 25:
            refs.append((c, ref, {w for w in ref.split() if len(w) > 3}))
    df: dict[str, int] = {}
    for _, _, words in refs:
        for w in words:
            df[w] = df.get(w, 0) + 1
    n_refs = max(len(refs), 1)

    def idf(w: str) -> float:
        return math.log(1 + n_refs / df.get(w, 1))

    results = []
    for c, ref, words in refs:
        total = sum(idf(w) for w in words) or 1.0
        best = 0.0
        for w_text, w_words in zip(windows, window_words, strict=True):
            coverage = sum(idf(w) for w in words & w_words) / total
            if coverage < 0.3:
                continue
            ratio = difflib.SequenceMatcher(None, ref, w_text, autojunk=False).ratio()
            best = max(best, 0.4 * ratio + 0.6 * coverage)
        status = "ok" if best >= 0.7 else ("changed" if best >= 0.45 else "missing")
        results.append(
            {
                "key": c.get("key"),
                "title": (c.get("title") or c.get("body", "").split("\n")[0])[:120],
                "score": round(best, 2),
                "status": status,
            }
        )
    total_n = len(results) or 1
    return {
        "clauses": results,
        "matched": sum(r["status"] == "ok" for r in results),
        "changed": [r for r in results if r["status"] == "changed"],
        "missing": [r for r in results if r["status"] == "missing"],
        "conformity": round(sum(r["status"] == "ok" for r in results) / total_n, 2),
    }
