from __future__ import annotations

import contextlib
import re
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_blob, encrypt_blob, sha256_hex
from app.core.errors import NotFound, ValidationFailed
from app.modules.files.models import StoredFile
from app.modules.files.storage import get_storage

ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "text/plain",
    "application/zip",
    "application/pkcs7-signature",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Magic-byte sniffing: never trust the client-supplied content type alone.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"PK\x03\x04", "application/zip"),  # also DOCX
    (b"ID3", "audio/mpeg"),
    (b"OggS", "audio/ogg"),
]


def sniff_mime(data: bytes, declared: str | None) -> str:
    head = data[:16]
    for sig, mime in _SIGNATURES:
        if head.startswith(sig):
            if mime == "application/zip" and declared and "wordprocessingml" in declared:
                return declared
            return mime
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if declared in ("text/plain", "image/heic", "audio/webm"):
        return declared
    raise ValidationFailed("Unsupported or unrecognised file type", code="file_type")


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE).strip() or "file"
    return name[-200:]


async def save_bytes(
    db: AsyncSession,
    *,
    data: bytes,
    filename: str,
    declared_mime: str | None,
    owner_id: uuid.UUID | None,
    purpose: str = "generic",
    trusted_mime: str | None = None,
) -> StoredFile:
    s = get_settings()
    if not data:
        raise ValidationFailed("Empty file", code="file_empty")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ValidationFailed(f"File exceeds {s.max_upload_mb} MB", code="file_too_large")
    mime = trusted_mime or sniff_mime(data, declared_mime)
    if mime not in ALLOWED_MIME:
        raise ValidationFailed("File type not allowed", code="file_type")

    file_id = uuid.uuid4()
    blob = encrypt_blob(data, aad=file_id.bytes)
    key = f"{purpose}/{datetime.now().strftime('%Y/%m')}/{file_id.hex}"
    await get_storage().put(key, blob.ciphertext)

    row = StoredFile(
        id=file_id,
        owner_id=owner_id,
        storage_key=key,
        original_name=_safe_name(filename),
        mime=mime,
        size=len(data),
        sha256=sha256_hex(data),
        encrypted=True,
        wrapped_key=blob.wrapped_key,
        purpose=purpose,
    )
    db.add(row)
    await db.flush()
    return row


async def get_file(db: AsyncSession, file_id: uuid.UUID) -> StoredFile:
    row = await db.get(StoredFile, file_id)
    if row is None:
        raise NotFound("File not found")
    return row


async def read_bytes(row: StoredFile, *, verify: bool = True) -> bytes:
    raw = await get_storage().get(row.storage_key)
    data = decrypt_blob(raw, row.wrapped_key, aad=row.id.bytes) if row.encrypted and row.wrapped_key else raw
    if verify and sha256_hex(data) != row.sha256:
        raise ValidationFailed("File integrity check failed", code="file_integrity")
    return data


async def delete_file(db: AsyncSession, file_id: uuid.UUID) -> None:
    """Remove the encrypted object and its row (used when a user deletes their own upload)."""
    row = await db.get(StoredFile, file_id)
    if row is None:
        return
    with contextlib.suppress(FileNotFoundError):
        await get_storage().delete(row.storage_key)
    await db.delete(row)
