"""Reference template of a contract type: the text a contract is checked against.

Two kinds of templates are trusted as a reference:
  * ``lexuz``        — official model form imported from lex.uz (four-eyes approved);
  * ``organization`` — the organization's own approved form (imported from its DOCX).

Both the deterministic comparison (scanner) and the AI review get the *rendered* text
(no Jinja syntax), split into numbered sub-clauses so that «3.1.2.» in the reference can
be matched against «3.1.2.» in an uploaded contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.contracts import generator
from app.modules.contracts.models import ContractType

LABELS = {
    "lexuz": "Rasmiy namunaviy shakl (lex.uz)",
    "organization": "Tashkilot tasdiqlagan shablon",
}
_NUMBERED = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s")


@dataclass(slots=True)
class Reference:
    kind: str
    label: str
    clauses: list[dict[str, str]]  # [{"key", "title", "body"}] — rendered, one numbered item each
    source: dict[str, Any] = field(default_factory=dict)

    @property
    def texts(self) -> list[str]:
        return [c["body"] for c in self.clauses]

    def as_template(self) -> dict[str, Any]:
        """Shape accepted by ``ai.compare_with_template``."""
        return {"clauses": self.clauses}


def _items(section: dict[str, Any]) -> list[dict[str, str]]:
    """Split a rendered section into its numbered items; unnumbered lines join the previous item."""
    out: list[dict[str, str]] = []
    for line in (section.get("text") or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _NUMBERED.match(line)
        if m or not out:
            out.append({"key": f"{section['key']}:{m.group(1) if m else len(out)}", "body": line})
        else:
            out[-1]["body"] += "\n" + line
    for it in out:
        it["title"] = it["body"].split("\n")[0][:120]
    return out


def reference_for(ctype: ContractType | None) -> Reference | None:
    if ctype is None or not ctype.template:
        return None
    src = ctype.source or {}
    kind = src.get("kind")
    if kind not in LABELS:
        return None
    content = generator.render_content(
        template=ctype.template,
        answers={},
        extra_clauses=[],
        type_code=ctype.code,
        language="uz",
        form_requirement="simple",
    )
    clauses = [it for s in content["sections"] for it in _items(s)]
    keep = ("url", "document_title", "annex", "edition_date") if kind == "lexuz" else ("title", "file", "imported_at")
    return Reference(kind=kind, label=LABELS[kind], clauses=clauses, source={k: src.get(k) for k in keep})
