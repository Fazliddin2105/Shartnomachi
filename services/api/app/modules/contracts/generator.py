"""Contract rendering: questionnaire answers -> structured content -> DOCX/PDF.

Templates are authored by legal experts and rendered in a Jinja2 *sandbox*
(no attribute access to Python internals, no imports) so CMS content can't
execute code.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from jinja2 import ChainableUndefined, TemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable, ValidationFailed


def _money(v: Any) -> str:
    try:
        d = Decimal(str(v))
    except Exception:
        return str(v or "")
    return f"{d:,.2f}".replace(",", " ").replace(".00", "")


def _date(v: Any) -> str:
    if isinstance(v, (date, datetime)):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10]).strftime("%d.%m.%Y")
        except ValueError:
            return v
    return str(v or "")


_ONES = ["", "bir", "ikki", "uch", "to‘rt", "besh", "olti", "yetti", "sakkiz", "to‘qqiz"]
_TENS = ["", "o‘n", "yigirma", "o‘ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to‘qson"]
_SCALES = ["", "ming", "million", "milliard", "trillion"]


def _triplet(n: int) -> list[str]:
    h, rest = divmod(n, 100)
    t, o = divmod(rest, 10)
    out = []
    if h:
        out += [_ONES[h], "yuz"]
    if t:
        out.append(_TENS[t])
    if o:
        out.append(_ONES[o])
    return out


def _words(v: Any) -> str:
    """Integer amount in Uzbek (Latin) words: 4500000 -> «to‘rt million besh yuz ming»."""
    try:
        n = int(Decimal(str(v)))
    except Exception:
        return ""
    if n == 0:
        return "nol"
    if n < 0 or n >= 10**15:
        return ""
    parts: list[str] = []
    scale = 0
    while n:
        n, chunk = divmod(n, 1000)
        if chunk:
            parts = [*_triplet(chunk), *([_SCALES[scale]] if scale else []), *parts]
        scale += 1
    return " ".join(parts)


_env = ImmutableSandboxedEnvironment(
    undefined=ChainableUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True
)
_env.filters["money"] = _money
_env.filters["date"] = _date
_env.filters["words"] = _words


def _render(src: str, ctx: dict[str, Any]) -> str:
    try:
        return _env.from_string(src).render(**ctx).strip()
    except TemplateError as e:
        raise ValidationFailed(f"Template error: {e}", code="template_error") from e


def _truthy(expr: str | None, ctx: dict[str, Any]) -> bool:
    if not expr:
        return True
    return _render("{% if " + expr + " %}1{% endif %}", ctx) == "1"


def render_content(
    *,
    template: dict[str, Any],
    answers: dict[str, Any],
    extra_clauses: list[dict[str, Any]],
    type_code: str,
    language: str,
    form_requirement: str,
) -> dict[str, Any]:
    ctx = {"a": answers, "party_a": answers.get("party_a", {}), "party_b": answers.get("party_b", {})}
    sections: list[dict[str, Any]] = []
    for c in template.get("clauses", []):
        if not _truthy(c.get("if"), ctx):
            continue
        sections.append(
            {
                "key": c["key"],
                "title": _render(c.get("title", ""), ctx),
                "text": _render(c.get("body", ""), ctx),
                "category": c.get("category"),
                **({"center_title": True} if c.get("center_title") else {}),
            }
        )
    if extra_clauses:
        n = len(sections) + 1
        lines = []
        for i, ec in enumerate(extra_clauses, start=1):
            body = _render(ec["body_template"], {**ctx, "p": ec.get("params", {})})
            lines.append(f"{n}.{i}. {body}")
        sections.append(
            {
                "key": "additional",
                "title": f"{n}. Qo'shimcha shartlar",
                "text": "\n".join(lines),
                "category": "additional",
            }
        )
    titles = template.get("party_titles") or {}
    parties = {
        side: {**({"role_title": titles[side]} if titles.get(side) else {}), **(ctx[f"party_{side.lower()}"] or {})}
        for side in ("A", "B")
    }
    content: dict[str, Any] = {
        "type_code": type_code,
        "language": language,
        "form_requirement": form_requirement,
        "title": _render(template.get("title", ""), ctx),
        "header": _render(template.get("header", ""), ctx),
        "preamble": _render(template.get("preamble", ""), ctx),
        "sections": sections,
        "parties": parties,
    }
    # Optional layout parts used by organization templates (kept out of the dict when unused,
    # so hashes of documents generated from older templates stay reproducible).
    if template.get("subheader"):
        content["subheader"] = _render(template["subheader"], ctx)
    if template.get("requisites"):
        content["requisites"] = template["requisites"]
    if template.get("closing"):
        content["closing"] = _render(template["closing"], ctx)
    return content


_REQ_LABELS = [
    ("name", "Nomi / F.I.Sh."),
    ("stir", "STIR"),
    ("pinfl", "JShShIR"),
    ("passport", "Pasport"),
    ("address", "Manzil"),
    ("bank", "Bank"),
    ("account", "H/r"),
    ("mfo", "MFO"),
    ("phone", "Telefon"),
]


def build_docx(content: dict[str, Any], *, version: int, sha256: str) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run(content.get("title", ""))
    run.bold = True
    run.font.size = Pt(14)
    if content.get("header"):
        doc.add_paragraph(content["header"])
    if content.get("subheader"):
        sp = doc.add_paragraph(content["subheader"])
        sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if content.get("preamble"):
        p = doc.add_paragraph(content["preamble"])
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for s in content.get("sections", []):
        if s["title"]:
            t = doc.add_paragraph()
            t.alignment = WD_ALIGN_PARAGRAPH.CENTER if s.get("center_title") else WD_ALIGN_PARAGRAPH.LEFT
            t.add_run(s["title"]).bold = True
        for line in s["text"].splitlines():
            if line.strip():
                para = doc.add_paragraph(line.strip())
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    req = content.get("requisites") or {}
    labels = [tuple(x) for x in req.get("labels", [])] or _REQ_LABELS
    signature = req.get("signature") or ["", "Imzo: ____________________"]
    doc.add_paragraph()
    doc.add_paragraph().add_run(req.get("title") or "Tomonlarning rekvizitlari va imzolari").bold = True
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    for i, side in enumerate(("A", "B")):
        party = content.get("parties", {}).get(side, {}) or {}
        cell = table.rows[0].cells[i]
        cell.text = ""
        cell.paragraphs[0].add_run(party.get("role_title") or f"Tomon {side}").bold = True
        for key, label in labels:
            if party.get(key):
                cell.add_paragraph(f"{label}: {party[key]}")
        for line in signature:
            cell.add_paragraph(line)

    if content.get("closing"):
        doc.add_paragraph()
        for line in content["closing"].splitlines():
            doc.add_paragraph(line)

    footer = doc.sections[0].footer.paragraphs[0]
    footer.text = f"LexLab • versiya {version} • SHA-256: {sha256}"
    footer.runs[0].font.size = Pt(7)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def docx_to_pdf(docx: bytes) -> bytes:
    """Headless LibreOffice conversion. Runs in a temp dir; never shells out with user input."""
    soffice = get_settings().soffice_path or shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise IntegrationUnavailable("PDF renderer (LibreOffice) is not installed", code="pdf_unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "contract.docx"
        src.write_bytes(docx)
        proc = await asyncio.create_subprocess_exec(
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmp,
            str(src),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except TimeoutError as e:
            proc.kill()
            raise IntegrationUnavailable("PDF conversion timed out", code="pdf_timeout") from e
        out = Path(tmp) / "contract.pdf"
        if proc.returncode != 0 or not out.exists():
            raise IntegrationUnavailable(
                f"PDF conversion failed: {err.decode(errors='ignore')[:200]}", code="pdf_failed"
            )
        return out.read_bytes()
