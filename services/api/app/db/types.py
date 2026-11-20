"""Portable column types.

PostgreSQL is the production target (JSONB, native UUID). SQLite is supported
for local development and tests via `with_variant` fallbacks.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt_field, encrypt_field

# JSONB on Postgres, JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class EncryptedString(TypeDecorator[str]):
    """AES-256-GCM encrypted text column (PINFL, passport, notes, ...)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else encrypt_field(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else decrypt_field(value)


class EncryptedJSON(TypeDecorator[Any]):
    """Encrypted JSON document (contract content, questionnaire answers)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return encrypt_field(json.dumps(value, ensure_ascii=False, default=str))

    def process_result_value(self, value: str | None, dialect: Dialect) -> Any:
        return None if value is None else json.loads(decrypt_field(value))


class StrEnumType(TypeDecorator[str]):
    """Stores enums as plain VARCHAR (no native PG enum => painless migrations)."""

    impl = String(32)
    cache_ok = True

    def __init__(self, enum_cls: type, length: int = 32) -> None:
        super().__init__(length)
        self.enum_cls = enum_cls

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return self.enum_cls(value).value  # type: ignore[no-any-return]

    def process_result_value(self, value: str | None, dialect: Dialect) -> Any:
        return None if value is None else self.enum_cls(value)
