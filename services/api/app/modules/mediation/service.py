"""Mediation requests: the user prepares an application to a mediator (O'RQ-482 «Mediatsiya to'g'risida»).

Flow: create (optionally from one of the user's contracts — parties and subject are prefilled) -> edit ->
optional AI help (neutral statement, claims, compromise options, lex.uz-grounded) -> download DOCX
(application + draft agreement on applying mediation, MQ 16). Nothing is sent anywhere by the platform.
"""

from __future__ import annotations

import io
import re
import uuid
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import llm, prompts
from app.ai import service as ai
from app.core.errors import NotFound, ValidationFailed
from app.core.timeutils import today_local
from app.modules.contracts import service as contracts
from app.modules.contracts.models import Contract, PartyRole
from app.modules.laws import corpus
from app.modules.mediation.models import MediationRequest
from app.modules.users.models import User

FIELDS = (
    "applicant_name", "applicant_address", "applicant_phone",
    "respondent_name", "respondent_address", "respondent_phone",
    "mediator_name", "mediator_org",
    "subject", "description", "claims", "desired_outcome", "amount", "city",
)  # fmt: skip
REQUIRED = {
    "applicant_name": "Arizachining F.I.Sh. (nomi)",
    "respondent_name": "Ikkinchi tomonning F.I.Sh. (nomi)",
    "subject": "Nizo predmeti",
    "description": "Nizo mazmuni",
}
LAW_ARTICLES = ("15", "16", "21", "23", "26", "28", "29", "291")


def _clean(form: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k in FIELDS:
        v = form.get(k)
        if v is None:
            continue
        v = re.sub(r"[ \t]+", " ", str(v)).strip()
        if v:
            out[k] = v[:4000]
    return out


def missing(form: dict[str, Any]) -> list[str]:
    m = [label for k, label in REQUIRED.items() if not (form.get(k) or "").strip()]
    if (form.get("description") or "").strip() and len(form["description"].strip()) < 20:
        m.append("Nizo mazmuni (kamida 20 belgi)")
    return m


def out(r: MediationRequest, contract_title: str | None = None) -> dict[str, Any]:
    form = r.form or {}
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id) if r.contract_id else None,
        "contract_title": contract_title,
        "status": r.status,
        "form": {k: form.get(k) for k in FIELDS},
        "missing": missing(form),
        "ai_draft": r.ai_draft or None,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "docx": f"/api/v1/mediation/requests/{r.id}/docx",
    }


async def _prefill_from_contract(db: AsyncSession, c: Contract, user: User) -> dict[str, str]:
    """Applicant = the user's side of the contract, respondent = the other side."""
    names = contracts.party_names(c)
    answers = c.answers or {}
    mine = next((p for p in c.parties if p.user_id == user.id), None)
    if mine is not None and mine.role in (PartyRole.A, PartyRole.B):
        side = mine.role.value
    else:
        side = "A" if c.owner_id == user.id else "B"
    other = "B" if side == "A" else "A"

    def party(s: str) -> dict[str, Any]:
        return answers.get(f"party_{s.lower()}") or {}

    pf = {
        "applicant_name": names.get(side) or (user.profile.full_name if user.profile else None),
        "applicant_address": party(side).get("address"),
        "applicant_phone": party(side).get("phone") or user.phone,
        "respondent_name": names.get(other),
        "respondent_address": party(other).get("address"),
        "respondent_phone": party(other).get("phone"),
        "subject": f"«{c.title}» shartnomasi bo'yicha kelishmovchilik",
        "amount": f"{c.total_amount:.0f}" if c.total_amount is not None else None,
        "city": answers.get("city"),
    }
    return {k: str(v) for k, v in pf.items() if v}


async def create(db: AsyncSession, user: User, form: dict[str, Any], contract_id: uuid.UUID | None) -> dict[str, Any]:
    data: dict[str, str] = {}
    title = None
    if contract_id is not None:
        c, _ = await contracts.load_for(db, contract_id, user)
        data = await _prefill_from_contract(db, c, user)
        title = c.title
    else:
        name = user.profile.full_name if user.profile else None
        data = {k: v for k, v in {"applicant_name": name, "applicant_phone": user.phone}.items() if v}
    data.update(_clean(form))  # what the user typed wins over the prefill
    r = MediationRequest(owner_id=user.id, contract_id=contract_id, form=data, ai_draft={})
    r.status = "ready" if not missing(data) else "draft"
    db.add(r)
    await db.flush()
    return out(r, title)


async def _own(db: AsyncSession, user: User, request_id: uuid.UUID) -> MediationRequest:
    r = await db.get(MediationRequest, request_id)
    if r is None or r.owner_id != user.id:
        raise NotFound("Mediation request not found")
    return r


async def _title(db: AsyncSession, r: MediationRequest) -> str | None:
    if r.contract_id is None:
        return None
    c = await db.get(Contract, r.contract_id)
    return c.title if c else None


async def get(db: AsyncSession, user: User, request_id: uuid.UUID) -> dict[str, Any]:
    r = await _own(db, user, request_id)
    return out(r, await _title(db, r))


async def list_for(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = list(
        await db.scalars(
            select(MediationRequest)
            .where(MediationRequest.owner_id == user.id)
            .order_by(MediationRequest.created_at.desc())
            .limit(100)
        )
    )
    return [out(r, await _title(db, r)) for r in rows]


async def update(db: AsyncSession, user: User, request_id: uuid.UUID, form: dict[str, Any]) -> dict[str, Any]:
    r = await _own(db, user, request_id)
    data = dict(r.form or {})
    for k in FIELDS:
        if k in form:  # explicit null / "" clears the field
            v = form[k]
            v = re.sub(r"[ \t]+", " ", str(v)).strip()[:4000] if v is not None else ""
            if v:
                data[k] = v
            else:
                data.pop(k, None)
    r.form = data
    r.status = "ready" if not missing(data) else "draft"
    await db.flush()
    return out(r, await _title(db, r))


async def delete(db: AsyncSession, user: User, request_id: uuid.UUID) -> None:
    r = await _own(db, user, request_id)
    await db.delete(r)
    await db.flush()


# --- AI help -----------------------------------------------------------------------------------------------


def _law_texts(question: str, ctype: Any | None) -> list[str]:
    arts = [corpus.article("mediation", n) for n in LAW_ARTICLES] if "mediation" in corpus.available() else []
    if ctype is not None:
        arts += corpus.articles_for(ctype.legal_refs, max_chars=600)
    seen = {(a["code"], str(a["number"])) for a in arts}
    for a in corpus.related(question, limit=3, max_chars=600):
        if (a["code"], str(a["number"])) not in seen:
            arts.append(a)
    trimmed = []
    for a in arts:
        t = a["text"]
        trimmed.append({**a, "text": t if len(t) <= 700 else t[:700].rsplit(" ", 1)[0] + " …"})
    return corpus.prompt_block(trimmed)


async def ai_help(db: AsyncSession, user: User, request_id: uuid.UUID) -> dict[str, Any]:
    r = await _own(db, user, request_id)
    form = r.form or {}
    if len((form.get("description") or "").strip()) < 20:
        raise ValidationFailed("Avval nizo mazmunini yozing (kamida 20 belgi)", code="mediation_need_description")
    contract_text, ctype = None, None
    if r.contract_id:
        c = await db.get(Contract, r.contract_id)
        if c is not None:
            ctype = c.contract_type
            contract_text = f"«{c.title}»\n" + prompts.clauses_block(await contracts._clauses_for_ai(db, c), 7000)
    law_texts = _law_texts(f"{form.get('subject', '')} {form.get('description', '')}", ctype)
    ans = await llm.ask_json(
        prompts.MEDIATION_SYSTEM,
        prompts.mediation_user(form=form, contract=contract_text, law_texts=law_texts),
        max_tokens=1200,
    )
    d = ans.data
    statement = ai._s(d.get("statement"), 4000)
    draft = {
        "subject": ai._s(d.get("subject"), 300),
        "statement": statement,
        "claims": [ai._s(x, 500) for x in (d.get("claims") or []) if isinstance(x, str) and x.strip()][:6],
        "options": [ai._s(x, 500) for x in (d.get("options") or []) if isinstance(x, str) and x.strip()][:5],
        "law_refs": ai._law_refs(d.get("law_refs"), statement or "", law_texts),
        "model": ans.model,
        "disclaimer": "AI taklifi — tekshirib, o'zingizga moslab qabul qiling.",
    }
    r.ai_draft = draft
    await db.flush()
    return draft


# --- DOCX ------------------------------------------------------------------------------------------------


def _p(doc: Any, text: str = "", *, bold: bool = False, center: bool = False, size: int | None = None) -> Any:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    if size:
        run.font.size = Pt(size)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return p


def _money(v: str | None) -> str | None:
    if not v:
        return None
    digits = re.sub(r"[^\d]", "", v)
    if not digits:
        return v
    return f"{int(digits):,}".replace(",", " ") + " so'm"


async def build_docx(db: AsyncSession, user: User, request_id: uuid.UUID) -> tuple[bytes, str]:
    r = await _own(db, user, request_id)
    f = r.form or {}
    gaps = missing(f)
    if gaps:
        raise ValidationFailed(
            "Arizani yuklab olish uchun majburiy maydonlarni to'ldiring", code="mediation_incomplete", details=gaps
        )
    title = await _title(db, r)
    today = today_local()
    blank = "____________________"

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(12)

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    head.add_run(f"Mediator: {f.get('mediator_name') or blank}\n")
    if f.get("mediator_org"):
        head.add_run(f"{f['mediator_org']}\n")
    head.add_run(f"Arizachi: {f['applicant_name']}\n")
    head.add_run(f"Manzil: {f.get('applicant_address') or blank}\n")
    head.add_run(f"Telefon: {f.get('applicant_phone') or blank}")

    _p(doc, "MEDIATORGA ARIZA", bold=True, center=True, size=14)
    _p(doc, "(nizoni mediatsiya tartib-taomili orqali hal etish to'g'risida)", center=True)

    _p(doc, "Ikkinchi tomon (nizo bo'yicha):", bold=True)
    _p(
        doc,
        f"{f['respondent_name']}; manzil: {f.get('respondent_address') or blank}; "
        f"telefon: {f.get('respondent_phone') or blank}.",
    )
    n = 1
    _p(doc, f"{n}. Nizo predmeti", bold=True)
    _p(doc, f["subject"])
    if title:
        n += 1
        _p(doc, f"{n}. Nizo kelib chiqqan shartnoma", bold=True)
        _p(doc, f"«{title}» (LexLab platformasida tuzilgan; nusxasi ilova qilinadi).")
    n += 1
    _p(doc, f"{n}. Nizo mazmuni", bold=True)
    _p(doc, f["description"])
    if f.get("amount"):
        _p(doc, f"Nizo summasi: {_money(f['amount'])}.")
    if f.get("claims"):
        n += 1
        _p(doc, f"{n}. Talablarim", bold=True)
        for line in [x.strip(" -•") for x in f["claims"].split("\n") if x.strip()]:
            _p(doc, f"— {line}")
    if f.get("desired_outcome"):
        n += 1
        _p(doc, f"{n}. Murosa bo'yicha taklifim", bold=True)
        _p(doc, f["desired_outcome"])
    n += 1
    _p(doc, f"{n}. Huquqiy asos", bold=True)
    _p(
        doc,
        "«Mediatsiya to'g'risida»gi O'zbekiston Respublikasi Qonuni (03.07.2018, O'RQ-482): mediatsiya taraflarning "
        "xohish-istagi asosida qo'llaniladi (15-modda); mediatsiyani qo'llash to'g'risidagi kelishuv yozma shaklda "
        "tuziladi (16-modda); mediatsiya davomida da'vo muddatining o'tishi to'xtatib turiladi (21-modda); "
        "mediatsiya o'ttiz kundan ortiq bo'lmagan muddatda tugallanishi kerak, zarur hollarda taraflar roziligi bilan "
        "o'ttiz kungacha uzaytirilishi mumkin (23-modda); mediatsiyaga taalluqli axborot maxfiy (26-modda); "
        "mediator xarajatlari, boshqacha kelishilmagan bo'lsa, teng ulushlarda to'lanadi (28-modda); natija "
        "bo'yicha yozma mediativ kelishuv tuziladi va u taraflar uchun majburiy (29, 29¹-moddalar).",
    )
    _p(
        doc,
        "Yuqoridagilarni inobatga olib, ikkinchi tomon bilan o'rtamizdagi nizoni mediatsiya tartib-taomili orqali "
        "hal etishda ko'maklashishingizni so'rayman. Mediatsiyada ishtirok etishga roziman.",
    )
    _p(doc, "Ilovalar:", bold=True)
    _p(
        doc,
        "1. Shartnoma nusxasi.\n2. To'lov va yozishmalarga oid hujjatlar (mavjud bo'lsa).\n3. Mediatsiyani qo'llash "
        "to'g'risidagi kelishuv loyihasi.",
    )
    _p(doc, f"{f.get('city') or ''}{', ' if f.get('city') else ''}{today.strftime('%d.%m.%Y')}")
    _p(doc, f"Arizachi: {f['applicant_name']}  ____________ (imzo)")

    doc.add_page_break()
    _p(doc, "MEDIATSIYANI QO'LLASH TO'G'RISIDAGI KELISHUV", bold=True, center=True, size=14)
    _p(doc, "(loyiha — «Mediatsiya to'g'risida»gi Qonunning 16-moddasi)", center=True)
    _p(doc, f"{f.get('city') or blank}                                        «___» __________ {today.year}-yil")
    _p(
        doc,
        f"Biz, quyida imzo chekuvchilar: {f['applicant_name']} (1-tomon) va {f['respondent_name']} (2-tomon), "
        "o'rtamizda kelib chiqqan nizoni mediatsiya tartib-taomilini amalga oshirish yo'li bilan hal etishga "
        "kelishib oldik:",
    )
    items = [
        f"Nizo predmeti: {f['subject']}.",
        f"Mediator: {f.get('mediator_name') or blank}. Mediator taraflar tomonidan birgalikda tanlanadi va "
        "mediatorlar reyestriga kiritilgan bo'lishi kerak.",
        "Mediatsiya tartib-taomili ushbu kelishuv imzolangan kundan boshlanadi va 30 (o'ttiz) kun ichida "
        "tugallanadi; zarur bo'lsa, taraflar roziligi bilan 30 kungacha uzaytirilishi mumkin.",
        "Mediator faoliyati uchun haq va xarajatlar taraflar tomonidan teng ulushlarda to'lanadi "
        "(boshqacha kelishilmagan bo'lsa).",
        "Mediatsiyaga taalluqli barcha axborot maxfiy hisoblanadi.",
        "Kelishuvga erishilsa, taraflar yozma mediativ kelishuv tuzadi; u taraflar uchun majburiy kuchga ega.",
    ]
    for i, t in enumerate(items, 1):
        _p(doc, f"{i}. {t}")
    _p(doc, "")
    _p(doc, f"1-tomon: {f['applicant_name']}  ____________ (imzo)")
    _p(doc, f"2-tomon: {f['respondent_name']}  ____________ (imzo)")

    buf = io.BytesIO()
    doc.save(buf)
    safe = re.sub(r"[^\w\-]+", "_", f["applicant_name"])[:40] or "ariza"
    return buf.getvalue(), f"mediatorga_ariza_{safe}_{today.isoformat()}.docx"
