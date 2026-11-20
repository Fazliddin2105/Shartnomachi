"""Official model form (lex.uz annex) -> platform template + questionnaire. Pure, no I/O.

Pipeline
  1. units      lines of the annex; table rows with several cells become parallel *columns*
                (a row of short captions such as «Ходим | Иш берувчи» names the columns)
  2. blanks     every run of 3+ underscores; «20__ йил «__» ____» is one date blank,
                «____-сон» is the document number; a following line «(…)» is the blank's hint
  3. fields     profile rules (hint / text-before / column / occurrence) map blanks to keys;
                the same key may appear many times but is asked once; unmatched -> generic field
  4. template   blanks become Jinja placeholders that fall back to the original underscores,
                so unanswered parts stay fillable by hand; lines are grouped into clauses
  5. script     optional Cyrillic -> Latin transliteration of everything except keys
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.translit import cyr_to_lat
from app.integrations.lexuz import Annex
from app.modules.scan.analysis import classify

BLANK = re.compile(r"_{3,}")
DATE = re.compile(r"(?:20|19)_*\d{0,2}_*\s*(?:йил|yil|г\.?)\s*[«\"“]\s*_+\s*[»\"”]\s*_+", re.IGNORECASE)
HINT = re.compile(r"^\((.*?)\)?$")
TOP_CLAUSE = re.compile(r"^(\d{1,2})\.\s")
NUMBER_AFTER = re.compile(r"^\s*-\s*(?:сон|son|№)", re.IGNORECASE)


# --- 1. units -------------------------------------------------------------------------------------


@dataclass(slots=True)
class Unit:
    text: str
    column: int | None = None
    column_title: str | None = None
    group: int | None = None  # consecutive multi-column rows share a group id
    footnote: bool = False

    @property
    def is_hint(self) -> bool:
        return self.text.startswith("(") and "_" not in self.text


def _is_caption_row(cells: list[str]) -> bool:
    return len(cells) >= 2 and all(c and "_" not in c and not c.startswith("(") and len(c) <= 40 for c in cells)


def build_units(annex: Annex) -> list[Unit]:
    units: list[Unit] = []
    group_id = 0
    for block in annex.blocks:
        if block.rows is None:
            units.extend(Unit(text=t, footnote=block.kind == "FOOTNOTE") for t in block.lines)
            continue
        titles: list[str] | None = None
        in_group = False
        for row in block.rows:
            cells = ["\n".join(c).strip() for c in row]
            filled = [c for c in cells if c]
            # a row continues an open column group (e.g. the hint row under «place | date»)
            multi = len(row) >= 2 and (len(filled) >= 2 or any("_" in c for c in cells[1:]) or in_group)
            if not multi:
                in_group = False
                for c in row:
                    units.extend(Unit(text=t) for t in c)
                continue
            if _is_caption_row(cells):
                titles = cells
                in_group = False
                continue
            if not in_group:
                group_id += 1
                in_group = True
            for idx, cell in enumerate(row):
                title = titles[idx] if titles and idx < len(titles) else None
                units.extend(Unit(text=t, column=idx, column_title=title, group=group_id) for t in cell)
    return [u for u in units if u.text.strip()]


# --- 2./3. blanks & fields -------------------------------------------------------------------------


@dataclass(slots=True)
class Occurrence:
    unit: int
    start: int
    end: int
    special: str | None  # date | number | None
    before: str
    hint: str | None = None
    key: str | None = None
    signature: bool = False
    render: str | None = None


@dataclass(slots=True)
class Field:
    key: str
    type: str
    label: str
    required: bool = False
    options: list[dict[str, str]] | None = None
    min: float | None = None
    max: float | None = None
    source: str = "generic"  # profile | generic
    hint: str | None = None

    def to_questionnaire(self) -> dict[str, Any]:
        d: dict[str, Any] = {"key": self.key, "label": self.label, "type": self.type, "required": self.required}
        if self.options:
            d["options"] = self.options
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.hint:
            d["help"] = self.hint
        return d


def find_blanks(units: list[Unit]) -> list[Occurrence]:
    occs: list[Occurrence] = []
    for i, u in enumerate(units):
        if u.is_hint:
            continue
        taken: list[tuple[int, int]] = []
        for m in DATE.finditer(u.text):
            taken.append((m.start(), m.end()))
            occs.append(Occurrence(i, m.start(), m.end(), "date", u.text[: m.start()]))
        prev_end = 0
        for m in BLANK.finditer(u.text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            special = "number" if NUMBER_AFTER.match(u.text[m.end() :]) else None
            occs.append(Occurrence(i, m.start(), m.end(), special, u.text[prev_end : m.start()]))
            prev_end = m.end()
    occs.sort(key=lambda o: (o.unit, o.start))
    # attach hints: a «(…)» line labels the last blank of the nearest previous line in the same column
    for i, u in enumerate(units):
        if not u.is_hint:
            continue
        hint = HINT.match(u.text).group(1).strip() if HINT.match(u.text) else u.text.strip("() ")
        for j in range(i - 1, -1, -1):
            if units[j].column != u.column or units[j].is_hint:
                continue
            line_occs = [o for o in occs if o.unit == j]
            if line_occs and line_occs[-1].hint is None:
                line_occs[-1].hint = hint
            break
    return occs


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", cyr_to_lat(text).lower().replace("'", "")).strip("_")
    return s[:40].rstrip("_") or "field"


def _matches(rule: dict[str, Any], occ: Occurrence, unit: Unit) -> bool:
    m = rule.get("match", {})
    if "special" in m and m["special"] != occ.special:
        return False
    if "hint" in m and not (occ.hint and re.search(m["hint"], occ.hint, re.IGNORECASE)):
        return False
    if "before" in m and not re.search(m["before"], occ.before, re.IGNORECASE):
        return False
    return not ("column" in m and not (unit.column_title and re.search(m["column"], unit.column_title, re.IGNORECASE)))


def resolve_fields(units: list[Unit], occs: list[Occurrence], rules: list[dict[str, Any]]) -> dict[str, Field]:
    fields: dict[str, Field] = {}
    seen: dict[int, int] = {}  # rule index -> how many blanks matched it so far (for "occurrence")
    repeat_counter: dict[str, int] = {}
    last_rule_in_column: dict[tuple[int | None, int | None], int] = {}
    for occ in occs:
        unit = units[occ.unit]
        chosen: int | None = None
        for idx, rule in enumerate(rules):
            if not _matches(rule, occ, unit):
                continue
            seen[idx] = seen.get(idx, 0) + 1
            want = rule.get("match", {}).get("occurrence")
            if want is not None and seen[idx] != want:
                continue
            if chosen is None:
                chosen = idx
        # rows of a repeated list without their own hint inherit the column's previous *repeatable* rule
        if chosen is None and occ.hint is None and unit.group is not None:
            inherited = last_rule_in_column.get((unit.group, unit.column))
            if inherited is not None and rules[inherited].get("repeatable"):
                chosen = inherited
            elif unit.column_title and not occ.before.strip():
                continue  # uncaptioned extra line in a requisites column: keep it as a plain line
        if (
            chosen is None
            and occ.special is None
            and occ.hint is None
            and not occ.before.strip()
            and unit.group is not None
            and unit.column_title
        ):
            continue
        if chosen is not None:
            rule = rules[chosen]
            if unit.group is not None:
                last_rule_in_column[(unit.group, unit.column)] = chosen
            if rule.get("signature"):
                occ.signature = True
                continue
            key = rule["key"]
            if rule.get("repeatable"):
                repeat_counter[key] = repeat_counter.get(key, 0) + 1
                key = f"{key}_{repeat_counter[key]}"
            occ.key, occ.render = key, rule.get("render")
            if key not in fields:
                fields[key] = Field(
                    key=key,
                    type=rule.get("type", "string"),
                    label=rule["label"] + (f" {repeat_counter[rule['key']]}" if rule.get("repeatable") else ""),
                    required=bool(rule.get("required")),
                    options=rule.get("options"),
                    min=rule.get("min"),
                    max=rule.get("max"),
                    source="profile",
                    hint=occ.hint,
                )
            continue
        # generic field: label from hint, else from the words right before the blank
        label = occ.hint or " ".join(re.sub(r"^\s*(\d+\.|[а-яa-z]\))\s*", "", occ.before).split()[-6:]) or "Maydon"
        base = f"f_{_slug(label)}"
        key, n = base, 1
        while key in fields and fields[key].label != label:
            n += 1
            key = f"{base}_{n}"
        occ.key = key
        fields.setdefault(key, Field(key=key, type="string", label=label.rstrip(":;,. "), hint=occ.hint))
    return fields


# --- 4. template -----------------------------------------------------------------------------------


def _escape_literal(text: str) -> str:
    return text.replace("{", "{{ '{' }}").replace("}", "{{ '}' }}") if ("{" in text or "}" in text) else text


def _lit(text: str) -> str:
    """Jinja string literal (labels contain the ASCII apostrophe: o'rindoshlik)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _present(v: str) -> str:
    return f'({v} is defined and {v} is not none and {v} != "")'


def _placeholder(occ: Occurrence, f: Field, original: str) -> str:
    """Expression-only Jinja (no {% %} blocks: trim_blocks would swallow the line break after them).
    Unanswered fields fall back to the original underscores so the paper form stays fillable."""
    v = "a." + f.key
    if occ.render:
        return occ.render.replace("{v}", v).replace("{blank}", _lit(original))
    if f.type == "date":
        return f"{{{{ ({v} | date) if {_present(v)} else {_lit(original)} }}}}"
    if f.type == "enum" and f.options:
        mapping = ", ".join(f"{_lit(o['value'])}: {_lit(o['label'])}" for o in f.options)
        return f"{{{{ {{{mapping}}}.get({v}) or {_lit(original)} }}}}"
    return f"{{{{ {v} if {_present(v)} else {_lit(original)} }}}}"


def render_unit(unit: Unit, idx: int, occs: list[Occurrence], fields: dict[str, Field]) -> str:
    text = unit.text
    out, pos = [], 0
    for o in sorted((o for o in occs if o.unit == idx), key=lambda o: o.start):
        before = text[pos : o.start]
        out.append(_escape_literal(before))
        if o.key and before and before[-1].isalpha():  # «Ходим______» -> "Xodim Aliyeva", not "XodimAliyeva"
            out.append(" ")
        original = text[o.start : o.end]
        if o.signature:  # wet/e-signature line keeps its caption: "_____ (sana va imzo)"
            out.append(f"{original} ({o.hint})" if o.hint else original)
        else:
            out.append(original if not o.key else _placeholder(o, fields[o.key], original))
        pos = o.end
    out.append(_escape_literal(text[pos:]))
    return "".join(out)


@dataclass(slots=True)
class Conversion:
    questionnaire: dict[str, Any]
    template: dict[str, Any]
    report: dict[str, Any]
    original_text: str
    field_order: list[str] = field(default_factory=list)


def convert(
    annex: Annex, profile: dict[str, Any] | None, generic_rules: list[dict[str, Any]], *, latin: bool = True
) -> Conversion:
    units = build_units(annex)
    occs = find_blanks(units)
    rules = list(generic_rules) + list((profile or {}).get("fields", []))
    fields = resolve_fields(units, occs, rules)
    tr = cyr_to_lat if latin else (lambda s: s)

    # render lines, grouping parallel columns column-by-column
    rendered: list[tuple[str, Unit]] = []
    i = 0
    while i < len(units):
        u = units[i]
        if u.group is None:
            if not u.is_hint:
                rendered.append((render_unit(u, i, occs, fields), u))
            i += 1
            continue
        j = i
        while j < len(units) and units[j].group == u.group:
            j += 1
        group = list(range(i, j))
        titled = any(units[k].column_title for k in group)
        columns = sorted({units[k].column for k in group}, key=lambda c: c or 0)
        if titled:
            for col in columns:
                col_units = [k for k in group if units[k].column == col]
                title = units[col_units[0]].column_title
                if title:
                    rendered.append((f"{title}:", units[col_units[0]]))
                for k in col_units:
                    if units[k].is_hint:
                        continue
                    line = render_unit(units[k], k, occs, fields)
                    keyed = [o for o in occs if o.unit == k and o.key]
                    if keyed and BLANK.fullmatch(units[k].text.strip() or "x"):
                        label = fields[keyed[0].key].label.split(" — ", 1)[-1]  # column title names the party
                        line = f"{label}: {line}"
                    rendered.append((line, units[k]))
        else:  # side-by-side cells -> one line per row
            rows: dict[int, list[str]] = {}
            row_idx: dict[int, int] = {}
            for k in group:
                if units[k].is_hint:
                    continue
                c = units[k].column or 0
                row_idx[c] = row_idx.get(c, 0) + 1
                rows.setdefault(row_idx[c], []).append(render_unit(units[k], k, occs, fields))
            rendered.extend(("    ".join(cells), units[i]) for _, cells in sorted(rows.items()))
        i = j

    # structure: title, header (until the first numbered clause), clauses, footnotes
    title, header, clauses, notes = "", [], [], []
    current: dict[str, Any] | None = None
    for line, unit in rendered:
        if unit.footnote:
            notes.append(line)
            continue
        if not title:
            title = line
            continue
        m = TOP_CLAUSE.match(unit.text) if unit.group is None else None
        if m:
            current = {"key": f"c{m.group(1)}", "title": "", "lines": [line]}
            clauses.append(current)
        elif current is None:
            header.append(line)
        elif unit.group is not None and unit.column_title and not current["key"].startswith("req"):
            current = {"key": "requisites", "title": "Rekvizitlar", "lines": [line]}
            clauses.append(current)
        elif (
            line.endswith(":")
            and unit.group is None
            and not TOP_CLAUSE.match(unit.text)
            and current["key"].startswith("c")
            and len(line) < 80
            and "реквизит" in line.lower()
        ):
            current = {"key": "requisites", "title": tr(line.rstrip(":")), "lines": []}
            clauses.append(current)
        else:
            current["lines"].append(line)
    if notes:
        clauses.append({"key": "notes", "title": "Izoh", "lines": notes})

    template = {
        "title": tr(title),
        "header": tr("\n".join(header)),
        "preamble": "",
        "clauses": [
            {
                "key": c["key"],
                "title": c["title"],
                "body": tr("\n".join(c["lines"])),
                "category": classify(cyr_to_lat("\n".join(c["lines"]))),
            }
            for c in clauses
        ],
    }

    # questionnaire: fields grouped by the clause where they first appear
    first_clause: dict[str, str] = {}
    unit_clause: dict[int, str] = {}
    clause_titles: dict[str, str] = {"header": "Shartnoma rekvizitlari"}
    cur_key = "header"
    for idx, u in enumerate(units):
        m = TOP_CLAUSE.match(u.text) if u.group is None else None
        if m:
            cur_key = f"c{m.group(1)}"
            clause_titles[cur_key] = cyr_to_lat(re.sub(BLANK, "…", u.text))[:70]
        elif u.column_title:
            cur_key = "requisites"
            clause_titles[cur_key] = "Tomonlar rekvizitlari"
        unit_clause[idx] = cur_key
    order: list[str] = []
    for o in occs:
        if o.key and o.key not in first_clause:
            first_clause[o.key] = unit_clause.get(o.unit, "header")
            order.append(o.key)
    sections: list[dict[str, Any]] = []
    for key in order:
        sec_key = first_clause[key]
        sec = next((s for s in sections if s["key"] == sec_key), None)
        if sec is None:
            sec = {"key": sec_key, "title": clause_titles.get(sec_key, sec_key), "fields": []}
            sections.append(sec)
        f = fields[key]
        q = f.to_questionnaire()
        q["label"] = tr(q["label"])
        if q.get("help"):
            q["help"] = tr(q["help"])
        if q.get("options"):
            q["options"] = [{"value": o["value"], "label": tr(o["label"])} for o in q["options"]]
        sec["fields"].append(q)

    questionnaire = {"sections": sections, "meta_fields": (profile or {}).get("meta_fields", {}), "imported": True}
    generic = [k for k, f in fields.items() if f.source == "generic"]
    report = {
        "blanks": len(occs),
        "fields": len(fields),
        "mapped_fields": [k for k, f in fields.items() if f.source == "profile"],
        "generic_fields": generic,
        "signature_blanks": sum(1 for o in occs if o.signature),
        "clauses": len(template["clauses"]),
        "warnings": (
            [f"{len(generic)} ta bo'sh joy profil qoidalariga mos kelmadi — nomlarini tekshiring"] if generic else []
        ),
    }
    return Conversion(questionnaire, template, report, annex.text, order)
