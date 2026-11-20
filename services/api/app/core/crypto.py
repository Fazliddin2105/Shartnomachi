"""Cryptographic primitives.

* AES-256-GCM envelope encryption: every blob gets its own random data key
  (DEK); the DEK is wrapped with the master key (KEK). Rotating the KEK only
  requires re-wrapping DEKs, not re-encrypting files.
* Field-level encryption for sensitive DB columns (see `app.db.types`).
* SHA-256 helpers and canonical JSON (stable hashing of contract content).
* HMAC helpers for OTP/refresh-token storage (never store secrets in clear).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_NONCE_LEN = 12
_VERSION = b"\x01"


def _kek() -> bytes:
    return get_settings().master_key_bytes


def _seal(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    return _VERSION + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _open(key: bytes, blob: bytes, aad: bytes | None = None) -> bytes:
    if not blob or blob[:1] != _VERSION:
        raise ValueError("Unsupported ciphertext version")
    nonce, ct = blob[1 : 1 + _NONCE_LEN], blob[1 + _NONCE_LEN :]
    return AESGCM(key).decrypt(nonce, ct, aad)


@dataclass(frozen=True, slots=True)
class EncryptedBlob:
    ciphertext: bytes
    wrapped_key: str  # base64(KEK-sealed DEK)


def encrypt_blob(data: bytes, *, aad: bytes | None = None) -> EncryptedBlob:
    dek = AESGCM.generate_key(bit_length=256)
    ciphertext = _seal(dek, data, aad)
    wrapped = base64.b64encode(_seal(_kek(), dek)).decode()
    return EncryptedBlob(ciphertext=ciphertext, wrapped_key=wrapped)


def decrypt_blob(ciphertext: bytes, wrapped_key: str, *, aad: bytes | None = None) -> bytes:
    dek = _open(_kek(), base64.b64decode(wrapped_key))
    return _open(dek, ciphertext, aad)


def encrypt_field(value: str) -> str:
    return base64.b64encode(_seal(_kek(), value.encode("utf-8"), b"field")).decode()


def decrypt_field(value: str) -> str:
    return _open(_kek(), base64.b64decode(value), b"field").decode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON encoding used for content hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def hmac_sha256(value: str, *, purpose: str) -> str:
    key = hashlib.sha256(_kek() + purpose.encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def random_digits(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))
