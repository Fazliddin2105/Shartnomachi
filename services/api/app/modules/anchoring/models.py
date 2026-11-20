from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutils import utcnow
from app.db.base import Base, UUIDPk
from app.db.types import EncryptedJSON, JSONType, StrEnumType


class LeafKind(StrEnum):
    CONTRACT_SIGNED = "contract.signed"  # all parties approved a version
    CASE_ATTACHMENT = "case.attachment"  # lawyer evidence file
    AUDIT_HEAD = "audit.head"  # head of the hash-chained audit log


class BatchStatus(StrEnum):
    PENDING = "pending"  # root computed, not sent yet
    SUBMITTED = "submitted"  # tx broadcast, waiting for confirmations
    CONFIRMED = "confirmed"
    FAILED = "failed"


class AnchorBatch(UUIDPk, Base):
    """One on-chain transaction = one Merkle root over many leaves."""

    __tablename__ = "anchor_batches"

    merkle_root: Mapped[str] = mapped_column(String(64), unique=True)
    leaf_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[BatchStatus] = mapped_column(StrEnumType(BatchStatus), default=BatchStatus.PENDING, index=True)
    network: Mapped[str] = mapped_column(String(32))
    chain_id: Mapped[int | None] = mapped_column(Integer)
    contract_address: Mapped[str | None] = mapped_column(String(42))
    tx_hash: Mapped[str | None] = mapped_column(String(66), unique=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    block_timestamp: Mapped[datetime | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column()
    confirmed_at: Mapped[datetime | None] = mapped_column()


class AnchorLeaf(UUIDPk, Base):
    """An integrity statement waiting for / included in an on-chain batch.

    `payload` is what the leaf commits to (document hashes, salted identity commitments,
    timestamps). It never leaves our servers except inside a proof package given to the
    parties. `secrets` holds the commitment salts (encrypted at rest).
    """

    __tablename__ = "anchor_leaves"

    kind: Mapped[LeafKind] = mapped_column(StrEnumType(LeafKind), index=True)
    ref_id: Mapped[str] = mapped_column(String(64), index=True)  # contract_version id / attachment id / audit id
    leaf_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256(canonical(payload))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    secrets: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("anchor_batches.id", ondelete="SET NULL"), index=True)
    leaf_index: Mapped[int | None] = mapped_column(Integer)
    proof: Mapped[list[dict[str, str]] | None] = mapped_column(JSONType)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
