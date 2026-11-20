"""lex.uz — national database of legislation (Qonunchilik ma'lumotlari milliy bazasi).

Fetches a document page and parses it into structured blocks. Page anatomy (observed 2026-11):

    <div class="ACT_TEXT lx_elem">                    <- element; class = semantic kind
      <div class="lx_elem2"> ...toolbar... </div>      <- UI chrome ("Hujjatga taklif yuborish", ...) — skipped
      <div name="7223175" id="7223175"> CONTENT </div> <- stable lex.uz element id + content
    </div>

Kinds used here: ACT_TITLE, ACT_TEXT, ACT_FORM, TEXT_HEADER_DEFAULT (chapter), ACT_TITLE_APPL (annex title),
APPL_BANNER_LANDSCAPE_TITLE ("N-ИЛОВА" banner), TABLE_* (tables — model forms live here), FOOTNOTE, COMMENT.
Metadata: <title>, .docHeader__item-label / -value, .lx_date_selected (current edition date),
.act_warning ("Hujjat kuchini yo'qotgan dd.mm.yyyy").

Official legal acts are not objects of copyright (Law "On copyright and related rights"), but we still
fetch politely: on demand / daily checks only, one request at a time, small pause, generic User-Agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html import unescape
from html.parser import HTMLParser

import httpx

from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable, NotFound, ValidationFailed

_VOID = {"br", "img", "input", "hr", "meta", "link", "col", "wbr", "source"}
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr"}
_DOC_ID = re.compile(r"^-?\d{3,10}$")
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_WS = re.compile(r"[ \t ​]+")


@dataclass(slots=True)
class Block:
    kind: str  # first CSS class, e.g. ACT_TEXT, TABLE_STD2
    element_id: str | None
    lines: list[str]
    rows: list[list[list[str]]] | None = None  # tables: rows -> cells -> lines

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(slots=True)
class Annex:
    number: int | None
    banner: str
    title: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass(slots=True)
class LexDocument:
    doc_id: str
    lang: str
    url: str
    title: str
    header: str
    in_force_from: date | None
    edition_date: date | None
    lost_force: bool
    lost_force_date: date | None
    blocks: list[Block]
    annexes: list[Annex]
    fetched_at: datetime

    def annex(self, number: int | None = None, title_contains: str | None = None) -> Annex:
        for a in self.annexes:
            if number is not None and a.number == number:
                return a
            if title_contains and title_contains.lower() in a.title.lower():
                return a
        raise NotFound("Annex not found in the lex.uz document", code="lexuz_annex_not_found")

    def content_hash(self) -> str:
        return hashlib.sha256("\n".join(b.text for b in self.blocks).encode()).hexdigest()


def _clean(s: str) -> str:
    return _WS.sub(" ", unescape(s)).strip()


def _date(s: str | None) -> date | None:
    m = _DATE.search(s or "")
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


class _Parser(HTMLParser):
    """Single pass: lx_elem blocks (with table structure) + header metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.meta: dict[str, list[str]] = {"title": [], "label": [], "value": [], "edition": [], "warning": []}
        self._meta_key: str | None = None
        self._meta_depth = 0
        # element state
        self._elem: Block | None = None
        self._depth = 0
        self._skip_at: int | None = None
        self._buf: list[str] = []
        # table state
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None
        self._cell_buf: list[str] = []
        self._depth_all = 0

    # -- helpers --
    def _flush_line(self) -> None:
        line = _clean("".join(self._buf))
        self._buf = []
        if line and self._elem is not None:
            self._elem.lines.append(line)

    def _flush_cell_line(self) -> None:
        line = _clean("".join(self._cell_buf))
        self._cell_buf = []
        if line and self._cell is not None:
            self._cell.append(line)

    # -- parser hooks --
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "title":
            self._meta_key, self._meta_depth = "title", 1
            return
        if self._elem is None:
            if tag in _VOID:
                return
            if "lx_elem" in cls.split():
                self._elem = Block(kind=cls.split()[0], element_id=None, lines=[])
                self._depth = 1
                return
            for key, marker in (
                ("label", "docHeader__item-label"),
                ("value", "docHeader__item-value"),
                ("edition", "lx_date_selected"),
                ("warning", "act_warning"),
            ):
                if marker in cls.split() and self._meta_key is None:
                    self._meta_key, self._meta_depth = key, 1
                    self.meta[key].append("")
                    return
            if self._meta_key is not None:
                self._meta_depth += 1
            return

        # inside an element
        if tag in _VOID:
            if tag == "br":
                (self._flush_cell_line if self._cell is not None else self._flush_line)()
            return
        self._depth += 1
        if self._skip_at is None and "lx_elem2" in cls.split():
            self._skip_at = self._depth
            return
        if self._skip_at is not None:
            return
        if a.get("id") and self._elem.element_id is None and tag == "div":
            self._elem.element_id = a["id"]
        if tag == "table":
            self._elem.rows = []
        elif tag == "tr" and self._elem.rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._cell_buf = [], []
        elif tag in _BLOCK:
            (self._flush_cell_line if self._cell is not None else self._flush_line)()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._meta_key == "title":
            self._meta_key = None
            return
        if self._elem is None:
            if self._meta_key is not None and tag not in _VOID:
                self._meta_depth -= 1
                if self._meta_depth == 0:
                    self._meta_key = None
            return
        if tag in _VOID:
            return
        if self._skip_at is not None:
            if self._depth == self._skip_at:
                self._skip_at = None
            self._depth -= 1
            return
        if tag in ("td", "th") and self._cell is not None:
            self._flush_cell_line()
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._elem.rows is not None:
            if any(self._row):
                self._elem.rows.append(self._row)
            self._row = None
        elif tag in _BLOCK and self._cell is None:
            self._flush_line()
        self._depth -= 1
        if self._depth == 0:
            self._flush_line()
            if self._elem.rows is not None:  # table text = row-major lines
                self._elem.lines = [ln for row in self._elem.rows for cell in row for ln in cell]
            self.blocks.append(self._elem)
            self._elem = None

    def handle_data(self, data: str) -> None:
        if self._elem is None:
            if self._meta_key is not None:
                if self._meta_key == "title":
                    self.meta["title"].append(data)
                else:
                    self.meta[self._meta_key][-1] += data
            return
        if self._skip_at is not None:
            return
        (self._cell_buf if self._cell is not None else self._buf).append(data)


_ANNEX_NO = re.compile(r"(\d+)\s*-\s*(?:ИЛОВА|ILOVA|ПРИЛОЖЕНИЕ)", re.IGNORECASE)


def _annexes(blocks: list[Block]) -> list[Annex]:
    out: list[Annex] = []
    cur: Annex | None = None
    for b in blocks:
        if b.kind == "APPL_BANNER_LANDSCAPE_TITLE" or b.kind.startswith("APPL_BANNER"):
            m = _ANNEX_NO.search(b.text)
            cur = Annex(number=int(m.group(1)) if m else None, banner=b.text, title="")
            out.append(cur)
            continue
        if cur is None:
            if b.kind == "ACT_TITLE_APPL":  # single unnumbered annex ("ILOVA")
                cur = Annex(number=1, banner="", title=b.text)
                out.append(cur)
            continue
        if b.kind == "ACT_TITLE_APPL" and not cur.title:
            cur.title = b.text
        elif b.kind not in ("COMMENT", "CHANGES_ORIGINS"):
            cur.blocks.append(b)
    return out


def parse(html: str, *, doc_id: str, lang: str, url: str) -> LexDocument:
    p = _Parser()
    p.feed(html)
    p.close()
    title = _clean("".join(p.meta["title"]))
    labels = [_clean(x) for x in p.meta["label"]]
    values = [_clean(x) for x in p.meta["value"]]
    in_force = None
    for lab, val in zip(labels[1:], values, strict=False):
        if "kuchga kirish" in lab.lower() or "вступления в силу" in lab.lower() or "кучга кириш" in lab.lower():
            in_force = _date(val)
    warning = " ".join(_clean(x) for x in p.meta["warning"])
    blocks = [b for b in p.blocks if b.kind not in ("COMMENT", "CHANGES_ORIGINS")]
    if not blocks:
        raise ValidationFailed("lex.uz page has no document body (layout changed?)", code="lexuz_parse_failed")
    return LexDocument(
        doc_id=doc_id,
        lang=lang,
        url=url,
        title=title,
        header=labels[0] if labels else "",
        in_force_from=in_force,
        edition_date=_date(" ".join(p.meta["edition"])),
        lost_force=bool(warning),
        lost_force_date=_date(warning),
        blocks=blocks,
        annexes=_annexes(blocks),
        fetched_at=datetime.now(UTC),
    )


# --- fetching ---------------------------------------------------------------------------------

_lock = asyncio.Lock()
_last_request = 0.0
_MIN_INTERVAL_S = 1.5
_transport: httpx.AsyncBaseTransport | None = None  # test hook


def configure_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def document_url(doc_id: str, lang: str = "uz", on_date: date | None = None) -> str:
    base = get_settings().lexuz_base_url.rstrip("/")
    url = f"{base}/{lang}/docs/{doc_id}"
    return url + (f"?ONDATE={on_date.strftime('%d.%m.%Y')}" if on_date else "")


async def fetch(doc_id: str, *, lang: str = "uz", on_date: date | None = None) -> LexDocument:
    global _last_request
    doc_id = str(doc_id).strip()
    if not _DOC_ID.match(doc_id):
        raise ValidationFailed("lex.uz document id must be numeric (e.g. 7220862 or -3532536)", code="lexuz_bad_id")
    if lang not in ("uz", "ru", "en"):
        raise ValidationFailed("lang must be uz, ru or en", code="lexuz_bad_lang")
    url = document_url(doc_id, lang, on_date)
    async with _lock:  # one request at a time, politely spaced
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request)
        if wait > 0 and _transport is None:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                transport=_transport,
                headers={"User-Agent": "LexLabImporter/1.0 (+legal templates sync)", "Accept-Language": lang},
            ) as client:
                r = await client.get(url)
        except httpx.HTTPError as e:
            raise IntegrationUnavailable("lex.uz is unreachable", code="lexuz_unavailable") from e
        finally:
            _last_request = time.monotonic()
    if r.status_code == 404:
        raise NotFound("Document not found on lex.uz", code="lexuz_not_found")
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        raise IntegrationUnavailable(f"lex.uz responded {r.status_code}", code="lexuz_unavailable")
    return parse(r.text, doc_id=doc_id, lang=lang, url=url)
