"""Text extraction: PDF text layer, DOCX, plain text, or OCR (Tesseract) for images/scans."""

from __future__ import annotations

import asyncio
import csv
import io
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from app.core.config import get_settings
from app.core.errors import IntegrationUnavailable, ValidationFailed

_MIN_TEXT_LAYER_CHARS = 200


@dataclass(frozen=True, slots=True)
class Extracted:
    text: str
    method: str  # text_layer | docx | plain | ocr
    confidence: float | None  # 0..100 for OCR


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValidationFailed("Encrypted PDFs are not supported", code="pdf_encrypted")
    return "\n".join((p.extract_text() or "") for p in reader.pages[:60])


def _docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _tesseract() -> str:
    cmd = get_settings().tesseract_cmd or shutil.which("tesseract")
    if not cmd:
        raise IntegrationUnavailable("OCR engine (Tesseract) is not installed", code="ocr_unavailable")
    return cmd


async def _run(*args: str, timeout: int = 120) -> bytes:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as e:
        proc.kill()
        raise IntegrationUnavailable("OCR timed out", code="ocr_timeout") from e
    if proc.returncode != 0:
        raise IntegrationUnavailable(f"OCR failed: {err.decode(errors='ignore')[:200]}", code="ocr_failed")
    return out


async def _ocr_image(path: Path) -> tuple[str, list[float]]:
    tsv = await _run(_tesseract(), str(path), "stdout", "-l", get_settings().tesseract_langs, "tsv")
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    confs: list[float] = []
    for row in csv.DictReader(io.StringIO(tsv.decode("utf-8", errors="ignore")), delimiter="\t"):
        word = (row.get("text") or "").strip()
        if not word:
            continue
        key = (row["page_num"], row["block_num"], row["par_num"], row["line_num"])
        lines.setdefault(key, []).append(word)
        try:
            c = float(row.get("conf", -1))
            if c >= 0:
                confs.append(c)
        except ValueError:
            pass
    return "\n".join(" ".join(ws) for ws in lines.values()), confs


async def ocr(data: bytes, mime: str) -> Extracted:
    with tempfile.TemporaryDirectory() as tmp:
        images: list[Path] = []
        if mime == "application/pdf":
            pdftoppm = shutil.which("pdftoppm")
            if not pdftoppm:
                raise IntegrationUnavailable("Scanned PDF needs pdftoppm (poppler) for OCR", code="ocr_unavailable")
            src = Path(tmp) / "in.pdf"
            src.write_bytes(data)
            await _run(pdftoppm, "-r", "300", "-png", "-l", "30", str(src), str(Path(tmp) / "p"))
            images = sorted(Path(tmp).glob("p*.png"))
        else:
            img = Path(tmp) / "in.img"
            img.write_bytes(data)
            images = [img]
        texts, confs = [], []
        for img in images:
            t, c = await _ocr_image(img)
            texts.append(t)
            confs.extend(c)
    conf = round(sum(confs) / len(confs), 1) if confs else 0.0
    return Extracted("\n\n".join(texts), "ocr", conf)


async def extract_text(data: bytes, mime: str) -> Extracted:
    if mime == "text/plain":
        return Extracted(data.decode("utf-8", errors="replace"), "plain", None)
    if mime.endswith("wordprocessingml.document"):
        return Extracted(await asyncio.to_thread(_docx_text, data), "docx", None)
    if mime == "application/pdf":
        text = await asyncio.to_thread(_pdf_text, data)
        if len(text.strip()) >= _MIN_TEXT_LAYER_CHARS:
            return Extracted(text, "text_layer", None)
        return await ocr(data, mime)
    if mime.startswith("image/"):
        return await ocr(data, mime)
    raise ValidationFailed("Unsupported file for scanning", code="scan_file_type")
