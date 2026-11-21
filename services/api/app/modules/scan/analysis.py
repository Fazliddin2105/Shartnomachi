"""Pure text pipeline: clean -> segment -> classify -> extract (uz-Latn, uz-Cyrl, ru)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# --- cleaning ---------------------------------------------------------------------

_APOS = str.maketrans({"ʻ": "'", "ʼ": "'", "`": "'", "‘": "'", "’": "'", "´": "'"})


def clean_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).translate(_APOS)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line wraps
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Drop page furniture: lone page numbers.
    text = "\n".join(ln for ln in text.split("\n") if not re.fullmatch(r"\s*(-?\s*\d{1,3}\s*-?)\s*", ln))
    return text.strip()


# --- segmentation --------------------------------------------------------------------

_CLAUSE_START = re.compile(
    r"^\s*(?:"
    r"(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+(?=\S)"  # 1.  1.1.  2.3.1)
    r"|(?P<band>\d{1,2})\s*-\s*(?:band|модда|modda|пункт)"  # 3-band
    r"|(?P<head>[A-ZА-ЯЎҚҒҲ'][A-ZА-ЯЎҚҒҲ' ,\-]{6,})$"  # UPPERCASE heading line
    r")",
    re.MULTILINE,
)


@dataclass(slots=True)
class Clause:
    index: int
    number: str | None
    heading: str | None
    text: str
    category: str | None = None
    extracted: dict[str, Any] = field(default_factory=dict)

    def as_ctx(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "number": self.number,
            "text": self.text,
            "category": self.category,
            "heading": self.heading,
        }


_TITLE_WORD = re.compile(r"shartnoma|шартнома|договор|kelishuv|келишув|соглашени", re.IGNORECASE)


def document_title(text: str) -> str | None:
    """The contract's own name from its heading, e.g. «PULLIK TIBBIY XIZMAT KO'RSATISH SHARTNOMASI»
    -> «Pullik tibbiy xizmat ko'rsatish shartnomasi». Looks at the first lines only."""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()][:8]
    for i, ln in enumerate(lines):
        if not _TITLE_WORD.search(ln) or len(ln) > 160 or re.match(r"^\d+(\.\d+)*[.)]\s", ln):
            continue
        title = ln
        # «ISHGA QABUL QILISH TO'G'RISIDA» / «MEHNAT SHARTNOMASI» split over two heading lines
        if i > 0 and lines[i - 1].isupper() and len(lines[i - 1]) < 80 and not _TITLE_WORD.search(lines[i - 1]):
            title = f"{lines[i - 1]} {ln}"
        title = re.sub(r"\s*№\s*\S*$", "", re.sub(r"\s+", " ", title)).strip(" .:-—")
        letters = [c for c in title if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
            title = title[:1].upper() + title[1:].lower()
        return title[:160] or None
    return None


def segment(text: str, *, max_len: int = 1500) -> list[Clause]:
    lines = text.split("\n")
    blocks: list[tuple[str | None, str | None, list[str]]] = []
    heading: str | None = None
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = _CLAUSE_START.match(s)
        if m and m.group("head") and len(s) < 80:
            heading = s.title()
            continue
        if m and (m.group("num") or m.group("band")):
            blocks.append((m.group("num") or m.group("band"), heading, [s]))
        elif blocks:
            blocks[-1][2].append(s)
        else:
            blocks.append((None, heading, [s]))
    if len(blocks) <= 1:  # unnumbered document: fall back to paragraphs/sentences
        paras = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.;])\s+(?=[A-ZА-ЯЎҚҒҲ])", text) if p.strip()]
        blocks = [(None, None, [p]) for p in paras]
    clauses: list[Clause] = []
    for num, head, parts in blocks:
        body = " ".join(parts)
        for chunk in _split_long(body, max_len):
            clauses.append(Clause(index=len(clauses), number=num, heading=head, text=chunk))
    return clauses


def _split_long(s: str, max_len: int) -> list[str]:
    if len(s) <= max_len:
        return [s]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.;])\s+", s):
        if len(cur) + len(sent) > max_len and cur:
            out.append(cur.strip())
            cur = ""
        cur += sent + " "
    if cur.strip():
        out.append(cur.strip())
    return out


# --- classification ---------------------------------------------------------------------

CATEGORIES: dict[str, list[str]] = {
    "subject": ["predmet", "предмет", "shartnoma predmeti"],
    "price": ["narx", "qiymat", "to'lov", "тўлов", "haq ", "summa", "стоимост", "цена", "оплат", "нарх"],
    "penalty": ["jarima", "penya", "neustoyka", "жарима", "пеня", "неустойк", "штраф", "пеня"],
    "termination": ["bekor qil", "muddatidan oldin", "бекор", "расторж", "prekrash", "прекращ"],
    "liability": ["javobgar", "жавобгар", "ответствен", "zarar", "убыт"],
    "confidentiality": ["maxfiy", "махфий", "конфиденц", "tijorat siri"],
    "force_majeure": ["fors-major", "форс-мажор", "форс мажор", "engib bo'lmas", "непреодолим"],
    "dispute": ["nizo", "низо", "спор", "sud ", "суд", "arbitraj"],
    "term": ["amal qiladi", "kuchga kiradi", "срок действ", "вступает в силу", "muddati"],
    "delivery": ["topshir", "yetkazib", "передач", "поставк", "qabul qilib ol"],
    "warranty": ["kafolat", "кафолат", "гаранти"],
}


def classify(text: str) -> str | None:
    t = text.lower()
    best, best_hits = None, 0
    for cat, kws in CATEGORIES.items():
        # A penalty clause nearly always mentions payment too; penalty keywords win the tie.
        hits = sum(t.count(k) for k in kws) * (2 if cat == "penalty" else 1)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


# --- extraction --------------------------------------------------------------------------

_DUTY = re.compile(r"\b(majbur|shart(?:dir)?|zimmasiga|мажбур|обязан|обязуется|должен)\w*", re.I)
_RIGHT = re.compile(r"\b(huquqli|haqli|huquqiga ega|ҳуқуқли|вправе|имеет право)\w*", re.I)
_AMOUNT = re.compile(
    r"(\d{1,3}(?:[  .]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(so'm|сўм|сум|uzs|usd|\$|aqsh dollar|доллар)", re.I
)
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|foiz|фоиз|процент)", re.I)
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_DAYS = re.compile(r"(\d{1,4})\s*(?:\(\w+\)\s*)?(kun|ish kuni|кун|дн|день|дней|календар)", re.I)
_MONTHLY = re.compile(r"(har oy|ҳар ой|ежемесячн|каждого месяца|oylik)", re.I)


def extract(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    amounts = []
    for m in _AMOUNT.finditer(text):
        whole = re.sub(r"[  .]", "", m.group(1))
        try:
            value = float(whole + ("." + m.group(2) if m.group(2) else ""))
        except ValueError:
            continue
        cur = m.group(3).lower()
        amounts.append({"value": value, "currency": "USD" if cur in ("usd", "$", "aqsh dollar", "доллар") else "UZS"})
    if amounts:
        out["amounts"] = amounts
    if pcts := [float(m.group(1).replace(",", ".")) for m in _PERCENT.finditer(text)]:
        out["percents"] = pcts
    dates = []
    for m in _DATE.finditer(text):
        try:
            dates.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat())
        except ValueError:
            continue
    if dates:
        out["dates"] = dates
    if days := [int(m.group(1)) for m in _DAYS.finditer(text)]:
        out["deadline_days"] = days
    if _MONTHLY.search(text):
        out["recurring"] = "monthly"
    return out


def duty_or_right(text: str) -> str | None:
    d, r = bool(_DUTY.search(text)), bool(_RIGHT.search(text))
    if d and not r:
        return "duty"
    if r and not d:
        return "right"
    if d and r:
        return "duty"  # mixed clauses: surface as obligation (more important to the user)
    return None


def detect_type(text: str, types: list[tuple[str, list[str]]]) -> str | None:
    """Pick the contract type whose *distinctive* keywords appear in the text.

    Each keyword found counts 1/df, where df is the number of types listing it: «ijaraga beruvchi»
    (shared by every lease type) barely moves the score, «noturar» or «notarius» decides it.
    Raw hit counts only break ties; at least 2 hits are required to claim a type.
    """
    t = text.lower()[:6000]
    lists = [(code, {k.lower() for k in kws if k}) for code, kws in types]
    df: dict[str, int] = {}
    for _, kws in lists:
        for k in kws:
            df[k] = df.get(k, 0) + 1
    best, best_key = None, (0.0, 0)
    for code, kws in lists:
        counts = {k: t.count(k) for k in kws}
        raw = sum(counts.values())
        key = (round(sum(1 / df[k] for k, n in counts.items() if n), 6), raw)
        if raw >= 2 and key > best_key:
            best, best_key = code, key
    return best


def missing_elements(text: str, required: list[dict[str, Any]]) -> list[dict[str, Any]]:
    t = text.lower()
    out = []
    for el in required:
        if not any(re.search(p, t, re.I) for p in el.get("patterns", [])):
            out.append(el)
    return out


RISK_LABELS = {"low": "Past xavf", "medium": "O'rta xavf", "high": "Yuqori xavf"}


def risk_percent(level: str | None, score: float | None) -> int:
    """0..100 for a gauge, banded by level so the needle never contradicts the label:
    low 0–33, medium 34–66, high 67–100; position inside the band grows with the score."""
    s = max(float(score or 0), 0.0)
    if level == "high":
        return min(100, round(67 + 33 * min(s, 15) / 15))
    if level == "medium":
        return round(34 + 32 * min(s, 6) / 6)
    return round(33 * min(s, 3) / 3)


def risk(red: int, yellow: int, missing: int) -> tuple[str, float]:
    score = red * 3 + yellow * 1.5 + missing * 1.0
    level = "high" if red or score >= 6 else "medium" if yellow or missing else "low"
    return level, round(score, 1)
