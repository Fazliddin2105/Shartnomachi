"""Scan report -> DOCX (the «hisobotni yuklab olish» button). Pure: report dict in, bytes out."""

from __future__ import annotations

import io
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

_SECTIONS = (
    ("red_clauses", "Qonunga zid bandlar"),
    ("risky_clauses", "Xavfli (qaltis) bandlar"),
    ("missing_elements", "Yetishmayotgan elementlar va shablondan farqlar"),
    ("your_obligations", "Sizning majburiyatlaringiz"),
    ("your_rights", "Sizning huquqlaringiz"),
    ("advice", "Maslahatlar"),
)


def build(report: dict[str, Any], *, title: str, created_at: str) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run("SHARTNOMA TAHLILI HISOBOTI")
    run.bold, run.font.size = True, Pt(14)

    o = report.get("overall") or {}
    meta = [
        ("Hujjat", title),
        ("Tahlil sanasi", created_at[:10]),
        ("Shartnoma turi", o.get("contract_type") or "aniqlanmagan"),
        ("Xavf darajasi", f"{o.get('risk_label', '')} ({o.get('risk_percent', '—')}/100)"),
        ("Qonunga zid / xavfli / yetishmaydi", f"{o.get('red', 0)} / {o.get('yellow', 0)} / {o.get('missing', 0)}"),
    ]
    tc = o.get("template_check") or None
    if tc:
        src = tc.get("source") or {}
        meta.append(
            ("Shablonga muvofiqlik", f"{round(100 * float(tc.get('conformity', 0)))}% — {src.get('label', '')}")
        )
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for k, v in meta:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = k, str(v)

    ai = report.get("ai") or {}
    if ai.get("status") == "done" and ai.get("summary"):
        doc.add_paragraph()
        doc.add_paragraph().add_run(f"AI xulosasi ({ai.get('model', '')})").bold = True
        doc.add_paragraph(str(ai["summary"]))
        for dv in ai.get("template_deviations") or []:
            doc.add_paragraph(
                f"• Shablondan farq ({dv.get('status')}): {dv.get('template_clause')} — {dv.get('comment')}"
            )

    for key, heading in _SECTIONS:
        items = report.get(key) or []
        if not items:
            continue
        doc.add_paragraph()
        doc.add_paragraph().add_run(f"{heading} ({len(items)})").bold = True
        for i, f in enumerate(items, start=1):
            p = doc.add_paragraph()
            label = f.get("ai_explanation") or f.get("explanation") or ""
            p.add_run(f"{i}. {label}").bold = key in ("red_clauses", "risky_clauses")
            if f.get("clause_text"):
                doc.add_paragraph(f"Band: «{f['clause_text']}»")
            if f.get("law_ref"):
                doc.add_paragraph(f"Asos: {f['law_ref']}")
            if f.get("suggestion"):
                doc.add_paragraph(f"Tavsiya: {f['suggestion']}")
            if f.get("user_decision"):
                doc.add_paragraph(
                    "Qaror: "
                    + {"agree": "rozilik bildirildi", "object": "e'tiroz bildirildi"}.get(
                        f["user_decision"], f["user_decision"]
                    )
                )

    doc.add_paragraph()
    doc.add_paragraph(report.get("disclaimer") or "").runs[0].italic = True
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
