"""Blockchain anchoring service.

Life cycle:  add_leaf()  ->  build_batch()  ->  submit_pending()  ->  confirm_submitted()
                (sync,            (every scheduler tick: Merkle root over pending leaves,
              in request)          relayer sends ONE tx per batch, waits N confirmations)

Privacy (spec §10, personal-data law): only the 32-byte Merkle root is public. Leaves stay in
our DB; identities inside leaves are *salted commitments* sha256(salt || identity) — a bare
hash of a 14-digit PINFL would be brute-forceable. Salts are encrypted and disclosed only to
the person they belong to (or to a court on request).
"""

from __future__ import annotations

import logging
import secrets as pysecrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AnchorBackend, get_settings
from app.core.crypto import canonical_json, sha256_hex
from app.core.errors import NotFound
from app.core.timeutils import utcnow
from app.modules.anchoring import chain as chain_mod
from app.modules.anchoring import merkle
from app.modules.anchoring.models import AnchorBatch, AnchorLeaf, BatchStatus, LeafKind
from app.modules.audit.models import AuditLog

log = logging.getLogger(__name__)

LEAF_VERSION = 1
MAX_SUBMIT_ATTEMPTS = 5


# --- commitments & leaves -------------------------------------------------------------------


def commit(identity: dict[str, Any]) -> tuple[str, str]:
    """Hiding + binding commitment. Returns (commitment_hex, salt_hex)."""
    salt = pysecrets.token_hex(16)
    return sha256_hex(bytes.fromhex(salt) + canonical_json(identity)), salt


def open_commitment(commitment: str, salt: str, identity: dict[str, Any]) -> bool:
    return sha256_hex(bytes.fromhex(salt) + canonical_json(identity)) == commitment


def leaf_hash(payload: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(payload))


async def add_leaf(
    db: AsyncSession,
    *,
    kind: LeafKind,
    ref_id: Any,
    payload: dict[str, Any],
    secrets: dict[str, Any] | None = None,
) -> AnchorLeaf:
    body = {"v": LEAF_VERSION, "kind": kind.value, "ref": str(ref_id), "at": utcnow().isoformat(), **payload}
    leaf = AnchorLeaf(kind=kind, ref_id=str(ref_id), leaf_hash=leaf_hash(body), payload=body, secrets=secrets)
    db.add(leaf)
    await db.flush()
    return leaf


# --- batching ----------------------------------------------------------------------------------


async def _add_audit_head(db: AsyncSession) -> None:
    """Anchor the head of the hash-chained audit log => the whole log becomes tamper-evident publicly."""
    head = await db.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
    if head is None:
        return
    last = await db.scalar(
        select(AnchorLeaf).where(AnchorLeaf.kind == LeafKind.AUDIT_HEAD).order_by(AnchorLeaf.created_at.desc()).limit(1)
    )
    if last is not None and last.payload.get("audit_hash") == head.hash:
        return
    await add_leaf(db, kind=LeafKind.AUDIT_HEAD, ref_id=head.id, payload={"audit_id": head.id, "audit_hash": head.hash})


async def build_batch(db: AsyncSession, *, include_audit_head: bool = True) -> AnchorBatch | None:
    s = get_settings()
    if include_audit_head:
        pending_docs = await db.scalar(
            select(AnchorLeaf.id).where(AnchorLeaf.batch_id.is_(None), AnchorLeaf.kind != LeafKind.AUDIT_HEAD).limit(1)
        )
        if pending_docs is not None:
            await _add_audit_head(db)
    leaves = list(
        await db.scalars(
            select(AnchorLeaf)
            .where(AnchorLeaf.batch_id.is_(None))
            .order_by(AnchorLeaf.created_at, AnchorLeaf.leaf_hash)
            .limit(s.anchor_batch_max_leaves)
        )
    )
    if not leaves:
        return None
    tree = merkle.build([bytes.fromhex(x.leaf_hash) for x in leaves])
    batch = AnchorBatch(
        merkle_root=tree.root.hex(), leaf_count=len(leaves), network=s.anchor_network, chain_id=s.evm_chain_id
    )
    db.add(batch)
    await db.flush()
    for i, (leaf, proof) in enumerate(zip(leaves, tree.proofs, strict=True)):
        leaf.batch_id, leaf.leaf_index = batch.id, i
        leaf.proof = [{"side": p.side, "hash": p.hash} for p in proof]
    await db.flush()
    return batch


async def submit_pending(db: AsyncSession, chain: chain_mod.AnchorChain) -> int:
    sent = 0
    for b in await db.scalars(select(AnchorBatch).where(AnchorBatch.status == BatchStatus.PENDING)):
        b.attempts += 1
        try:
            b.tx_hash = await chain.submit(bytes.fromhex(b.merkle_root), b.leaf_count)
        except chain_mod.AnchorRejected as e:
            if (e.details or {}).get("error") == "AlreadyAnchored":  # e.g. a retry after a lost response
                ts = await chain.anchored_at(bytes.fromhex(b.merkle_root))
                b.status, b.confirmed_at = BatchStatus.CONFIRMED, utcnow()
                b.block_timestamp = datetime.fromtimestamp(ts, UTC) if ts else None
            else:  # NotRelayer / EmptyRoot: configuration error, retrying won't help
                b.status, b.last_error = BatchStatus.FAILED, e.message
                log.error("anchor_rejected", extra={"batch": str(b.id), "error": e.details})
            continue
        except Exception as e:
            b.last_error = str(e)[:500]
            if b.attempts >= MAX_SUBMIT_ATTEMPTS:
                b.status = BatchStatus.FAILED
            log.warning("anchor_submit_failed", extra={"batch": str(b.id), "error": b.last_error})
            continue
        b.status, b.submitted_at = BatchStatus.SUBMITTED, utcnow()
        b.contract_address, b.chain_id = chain.contract_address, chain.chain_id
        sent += 1
    await db.flush()
    return sent


async def confirm_submitted(db: AsyncSession, chain: chain_mod.AnchorChain) -> int:
    need = get_settings().anchor_confirmations
    done = 0
    for b in await db.scalars(select(AnchorBatch).where(AnchorBatch.status == BatchStatus.SUBMITTED)):
        assert b.tx_hash is not None
        r = await chain.receipt(b.tx_hash)
        if r is None:
            continue
        if not r.success:
            # Reverted. If the root is anchored anyway (e.g. retried tx), that's fine; else retry.
            ts = await chain.anchored_at(bytes.fromhex(b.merkle_root))
            if not ts:
                b.status, b.tx_hash, b.last_error = BatchStatus.PENDING, None, "transaction reverted"
                continue
        if r.confirmations < need:
            continue
        b.status, b.confirmed_at = BatchStatus.CONFIRMED, utcnow()
        b.block_number = r.block_number
        b.block_timestamp = datetime.fromtimestamp(r.block_timestamp, UTC)
        done += 1
    await db.flush()
    return done


async def run_cycle(db: AsyncSession) -> dict[str, int]:
    if get_settings().anchor_backend == AnchorBackend.DISABLED:
        return {}
    chain = chain_mod.get_chain()
    built = await build_batch(db)
    sent = await submit_pending(db, chain)
    confirmed = await confirm_submitted(db, chain)
    return {"built": int(built is not None), "submitted": sent, "confirmed": confirmed}


# --- proofs ------------------------------------------------------------------------------------


async def proof_package(
    db: AsyncSession, *, kind: LeafKind, ref_id: Any, opening_for: str | None = None
) -> dict[str, Any]:
    """Self-contained evidence: leaf + Merkle path + chain coordinates (+ the viewer's own opening)."""
    leaf = await db.scalar(
        select(AnchorLeaf)
        .where(AnchorLeaf.kind == kind, AnchorLeaf.ref_id == str(ref_id))
        .order_by(AnchorLeaf.created_at.desc())
        .limit(1)
    )
    if leaf is None:
        raise NotFound("No blockchain anchor for this object", code="anchor_not_found")
    batch = await db.get(AnchorBatch, leaf.batch_id) if leaf.batch_id else None
    s = get_settings()
    pkg: dict[str, Any] = {
        "leaf": {"payload": leaf.payload, "leaf_hash": leaf.leaf_hash},
        "status": batch.status.value if batch else "queued",
        "merkle": None,
        "chain": None,
    }
    if batch is not None:
        pkg["merkle"] = {
            "algorithm": "sha256-rfc6962",
            "root": batch.merkle_root,
            "leaf_index": leaf.leaf_index,
            "proof": leaf.proof,
            "verified": merkle.verify(
                bytes.fromhex(leaf.leaf_hash), leaf.proof or [], bytes.fromhex(batch.merkle_root)
            ),
        }
        if batch.tx_hash:
            pkg["chain"] = {
                "network": batch.network,
                "chain_id": batch.chain_id,
                "contract": batch.contract_address,
                "tx_hash": batch.tx_hash,
                "block_number": batch.block_number,
                "block_timestamp": batch.block_timestamp.isoformat() if batch.block_timestamp else None,
                "explorer_url": s.anchor_explorer_tx_url.format(tx=batch.tx_hash),
                "verify_call": f"anchoredAt(0x{batch.merkle_root})",
            }
    if opening_for and leaf.secrets and opening_for in leaf.secrets:
        pkg["your_commitment_opening"] = leaf.secrets[opening_for]
    return pkg


async def verify_package(
    *, proof: list[dict[str, str]], root: str, payload: dict[str, Any] | None, leaf_hash_hex: str | None
) -> dict[str, Any]:
    """Public, stateless verification (used by courts / counterparties)."""
    lh = leaf_hash(payload) if payload is not None else leaf_hash_hex
    if not lh:
        raise NotFound("Either payload or leaf_hash is required", code="anchor_input_missing")
    ok = merkle.verify(bytes.fromhex(lh), proof, bytes.fromhex(root))
    onchain: dict[str, Any] | None = None
    if get_settings().anchor_backend != AnchorBackend.DISABLED:
        ts = await chain_mod.get_chain().anchored_at(bytes.fromhex(root))
        onchain = {"anchored": bool(ts), "timestamp": datetime.fromtimestamp(ts, UTC).isoformat() if ts else None}
    return {
        "leaf_hash": lh,
        "merkle_ok": ok,
        "onchain": onchain,
        "valid": ok and (onchain is None or onchain["anchored"]),
    }
