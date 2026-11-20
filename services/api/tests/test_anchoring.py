"""Blockchain anchoring: Merkle math, the real Solidity contract on an in-memory EVM, end-to-end flow."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from web3 import EthereumTesterProvider, Web3

from app.core.config import AnchorBackend, get_settings
from app.db.session import session_scope
from app.modules.anchoring import chain as chain_mod
from app.modules.anchoring import merkle, service
from app.modules.anchoring.models import AnchorBatch, AnchorLeaf, BatchStatus, LeafKind
from tests.conftest import API, LAWYER, login, login_privileged
from tests.test_api_eimzo import _pending_contract

# --- pure ------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 9, 16, 33])
def test_merkle_proofs_for_every_leaf(n: int) -> None:
    leaves = [bytes([i]) * 32 for i in range(n)]
    tree = merkle.build(leaves)
    for leaf, proof in zip(leaves, tree.proofs, strict=True):
        assert merkle.verify(leaf, proof, tree.root)
    if n > 1:
        assert not merkle.verify(b"\xff" * 32, tree.proofs[0], tree.root)  # foreign leaf
        flipped = [merkle.ProofStep("R" if p.side == "L" else "L", p.hash) for p in tree.proofs[0]]
        assert not merkle.verify(leaves[0], flipped, tree.root)  # wrong positions


def test_leaf_is_not_an_internal_node() -> None:
    # domain separation: an internal node can't be presented as a leaf (second-preimage resistance)
    a, b = b"\x01" * 32, b"\x02" * 32
    tree = merkle.build([a, b])
    assert not merkle.verify(merkle.internal_node(merkle.leaf_node(a), merkle.leaf_node(b)), [], tree.root)


def test_commitment_hides_and_binds() -> None:
    identity = {"pinfl": "31234567890123", "user_id": "u1"}
    c1, salt = service.commit(identity)
    c2, _ = service.commit(identity)
    assert c1 != c2  # salted: same person -> unlinkable commitments
    assert service.open_commitment(c1, salt, identity)
    assert not service.open_commitment(c1, salt, {**identity, "pinfl": "31234567890124"})


# --- real contract on an in-memory EVM -----------------------------------------------------------


@pytest.fixture
def evm(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Web3, chain_mod.EvmChain, str]]:
    provider = EthereumTesterProvider()
    w3 = Web3(provider)
    keys = provider.ethereum_tester.backend.account_keys
    relayer_key, stranger_key = keys[0].to_hex(), keys[1].to_hex()
    address = chain_mod.deploy(w3, relayer_key)
    chain = chain_mod.EvmChain(w3, address, relayer_key)
    chain_mod.set_chain(chain)
    s = get_settings()
    monkeypatch.setattr(s, "anchor_backend", AnchorBackend.EVM)
    monkeypatch.setattr(s, "anchor_confirmations", 1)
    yield w3, chain, stranger_key
    chain_mod.set_chain(None)


async def test_contract_rules(evm: tuple[Web3, chain_mod.EvmChain, str]) -> None:
    w3, chain, stranger_key = evm
    root = b"\x11" * 32
    tx = await chain.submit(root, 3)
    r = await chain.receipt(tx)
    assert r is not None and r.success and await chain.anchored_at(root) == r.block_timestamp
    assert chain.contract.functions.totalBatches().call() == 1

    stranger = chain_mod.EvmChain(w3, chain.contract_address, stranger_key)
    for c, r, expected in (
        (chain, root, "AlreadyAnchored"),
        (stranger, b"\x22" * 32, "NotRelayer"),
        (chain, b"\x00" * 32, "EmptyRoot"),
    ):
        with pytest.raises(chain_mod.AnchorRejected) as exc:
            await c.submit(r, 1)
        assert exc.value.details == {"error": expected}
    assert await chain.anchored_at(b"\x33" * 32) == 0


async def test_end_to_end_contract_and_evidence(client: AsyncClient, evm: Any) -> None:
    # 1) two parties sign a contract (OTP) -> a leaf is queued at activation
    a, b = await login(client, "+998961000001"), await login(client, "+998961000002")
    cid = await _pending_contract(client, a, b, "+998961000002")
    sha = (await client.get(f"{API}/contracts/{cid}/versions", headers=a)).json()[0]["sha256"]
    for h in (a, b):
        await client.post(f"{API}/contracts/{cid}/approve/otp", headers=h)
        r = await client.post(
            f"{API}/contracts/{cid}/approve", headers=h, json={"method": "otp", "code": "123456", "sha256": sha}
        )
        assert r.status_code == 200, r.text
    queued = (await client.get(f"{API}/contracts/{cid}/versions/1/anchor", headers=a)).json()
    assert queued["status"] == "queued" and queued["chain"] is None

    # 2) a lawyer stores evidence -> another leaf
    lawyer = await login(client, LAWYER)
    case = (await client.post(f"{API}/cases", headers=lawyer, json={"title": "Anchored case"})).json()
    step = (await client.post(f"{API}/cases/{case['id']}/steps", headers=lawyer, json={"title": "Dalil"})).json()
    att = (
        await client.post(
            f"{API}/cases/{case['id']}/attachments",
            headers=lawyer,
            data={"step_id": step["id"]},
            files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"1" * 40, "image/png")},
        )
    ).json()

    # 3) one scheduler tick: Merkle root -> relayer tx -> confirmation (users never touch crypto)
    async with session_scope() as db:
        stats = await service.run_cycle(db)
    assert stats == {"built": 1, "submitted": 1, "confirmed": 1}
    async with session_scope() as db:
        batch = await db.scalar(select(AnchorBatch).order_by(AnchorBatch.created_at.desc()).limit(1))
        assert batch is not None and batch.status == BatchStatus.CONFIRMED and batch.leaf_count >= 3
        kinds = set(await db.scalars(select(AnchorLeaf.kind).where(AnchorLeaf.batch_id == batch.id)))
        assert {LeafKind.CONTRACT_SIGNED, LeafKind.CASE_ATTACHMENT, LeafKind.AUDIT_HEAD} <= kinds

    # 4) proof package for party A: confirmed, Merkle path valid, A's own opening only
    pkg = (await client.get(f"{API}/contracts/{cid}/versions/1/anchor", headers=a)).json()
    assert pkg["status"] == "confirmed" and pkg["merkle"]["verified"]
    assert pkg["chain"]["tx_hash"].startswith("0x") and pkg["chain"]["block_number"]
    payload = pkg["leaf"]["payload"]
    assert payload["content_sha256"] == sha and len(payload["signers"]) == 2
    assert "pinfl" not in json.dumps(payload) and "+99896" not in json.dumps(payload)  # nothing personal in the leaf
    opening = pkg["your_commitment_opening"]
    assert service.open_commitment(opening["commitment"], opening["salt"], opening["identity"])
    assert opening["commitment"] in [s["commitment"] for s in payload["signers"]]

    # 5) anyone (a court) verifies without an account: Merkle math + on-chain root
    body = {"root": pkg["merkle"]["root"], "proof": pkg["merkle"]["proof"], "payload": payload}
    v = (await client.post(f"{API}/anchors/verify", json=body)).json()
    assert v["valid"] and v["onchain"]["anchored"]
    forged = {**body, "payload": {**payload, "content_sha256": "0" * 64}}
    assert (await client.post(f"{API}/anchors/verify", json=forged)).json()["valid"] is False

    # 6) evidence bundle carries the blockchain proof for each file
    proof = (await client.get(f"{API}/cases/{case['id']}/attachments/{att['id']}/anchor", headers=lawyer)).json()
    assert proof["leaf"]["payload"]["file_sha256"] == att["sha256"] and proof["status"] == "confirmed"
    zf = zipfile.ZipFile(io.BytesIO((await client.get(f"{API}/cases/{case['id']}/export", headers=lawyer)).content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["steps"][0]["attachments"][0]["blockchain"]["chain"]["tx_hash"] == proof["chain"]["tx_hash"]

    admin = await login_privileged(client, "+998900000001")
    batches = (await client.get(f"{API}/admin/anchors", headers=admin)).json()
    assert batches[0]["status"] == "confirmed"


class _BrokenChain:
    chain_id, contract_address = 1, "0x" + "0" * 40

    async def submit(self, root: bytes, leaf_count: int) -> str:
        raise ConnectionError("RPC down")

    async def receipt(self, tx_hash: str) -> None:
        return None

    async def anchored_at(self, root: bytes) -> int:
        return 0


async def test_rpc_outage_is_retried_then_marked_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "anchor_backend", AnchorBackend.EVM)
    chain_mod.set_chain(_BrokenChain())
    try:
        async with session_scope() as db:
            await service.add_leaf(db, kind=LeafKind.AUDIT_HEAD, ref_id="manual", payload={"x": 1})
            for _ in range(service.MAX_SUBMIT_ATTEMPTS):
                await service.run_cycle(db)
            failed = await db.scalar(select(AnchorBatch).where(AnchorBatch.status == BatchStatus.FAILED))
            assert failed is not None and failed.attempts == service.MAX_SUBMIT_ATTEMPTS
            assert "RPC down" in (failed.last_error or "")
    finally:
        chain_mod.set_chain(None)
