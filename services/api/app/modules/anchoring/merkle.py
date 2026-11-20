"""SHA-256 Merkle tree with RFC 6962-style domain separation (pure, no I/O).

* leaf node      = SHA256(0x00 || leaf)
* internal node  = SHA256(0x01 || left || right)
* odd node at a level is promoted unchanged (no duplication => no CVE-2012-2459 style ambiguity)

Verification needs only the leaf, the proof path and the root, so anyone (a court, the
other party) can check inclusion independently, then check the root on-chain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

Side = Literal["L", "R"]


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_node(leaf: bytes) -> bytes:
    return _h(b"\x00" + leaf)


def internal_node(left: bytes, right: bytes) -> bytes:
    return _h(b"\x01" + left + right)


@dataclass(frozen=True, slots=True)
class ProofStep:
    side: Side  # where the sibling sits relative to the running hash
    hash: str  # hex


@dataclass(frozen=True, slots=True)
class MerkleTree:
    root: bytes
    proofs: list[list[ProofStep]]


def build(leaves: list[bytes]) -> MerkleTree:
    if not leaves:
        raise ValueError("Merkle tree needs at least one leaf")
    level = [leaf_node(x) for x in leaves]
    # positions[i] = index of leaf i's ancestor in the current level
    positions = list(range(len(leaves)))
    proofs: list[list[ProofStep]] = [[] for _ in leaves]
    while len(level) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(internal_node(level[i], level[i + 1]))
            else:
                nxt.append(level[i])  # promote odd node
        for leaf_idx, pos in enumerate(positions):
            sibling = pos ^ 1
            if sibling < len(level):
                side: Side = "L" if sibling < pos else "R"
                proofs[leaf_idx].append(ProofStep(side, level[sibling].hex()))
            positions[leaf_idx] = pos // 2
        level = nxt
    return MerkleTree(root=level[0], proofs=proofs)


def verify(leaf: bytes, proof: list[ProofStep] | list[dict[str, str]], root: bytes) -> bool:
    node = leaf_node(leaf)
    for step in proof:
        side, sib = (step.side, step.hash) if isinstance(step, ProofStep) else (step["side"], step["hash"])
        sibling = bytes.fromhex(sib)
        node = internal_node(sibling, node) if side == "L" else internal_node(node, sibling)
    return node == root
