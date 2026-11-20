"""EVM chain adapter (Polygon Amoy testnet by default; any EVM network works).

"Gasless" for users: the platform's relayer wallet signs and pays for every anchor
transaction. End users never see a wallet, seed phrase or gas fee.

web3.py is synchronous here (works identically with HTTPProvider and the in-memory
EthereumTesterProvider used in tests); calls run in a worker thread.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.errors import AppError, IntegrationUnavailable

ARTIFACT = Path(__file__).resolve().parents[5] / "packages" / "contracts" / "build" / "LexLabAnchor.json"


@lru_cache
def artifact() -> dict[str, Any]:
    path = Path(get_settings().legal_content_dir).parent / "contracts" / "build" / "LexLabAnchor.json"
    for p in (path, ARTIFACT):
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    raise IntegrationUnavailable("LexLabAnchor artifact not found (run the contract build)", code="anchor_unavailable")


class AnchorRejected(AppError):
    """The contract reverted with one of its custom errors (NotRelayer, AlreadyAnchored, EmptyRoot)."""

    status_code = 409
    code = "anchor_rejected"


@lru_cache
def _error_selectors() -> dict[str, str]:
    from eth_utils import keccak

    return {
        keccak(text=f"{item['name']}()")[:4].hex(): item["name"]
        for item in artifact()["abi"]
        if item.get("type") == "error" and not item.get("inputs")
    }


def decode_revert(exc: BaseException) -> str | None:
    """Map a revert (any provider/exception flavour) to the contract's custom error name."""
    blobs: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:  # walk __cause__/__context__ (web3 wraps provider errors)
        seen.add(id(cur))
        for item in (*getattr(cur, "args", ()), getattr(cur, "data", None), str(cur)):
            if isinstance(item, bytes):
                blobs.append(item.hex())
            elif item:
                text = str(item)
                blobs.append(text)
                # e.g. "execution reverted: b'\xa0\tL\xe3'" -> decode the bytes literal
                for lit in re.findall(r"b'(?:[^'\\]|\\.)*'|b\"(?:[^\"\\]|\\.)*\"", text):
                    with contextlib.suppress(ValueError, SyntaxError):
                        blobs.append(ast.literal_eval(lit).hex())
        cur = cur.__cause__ or cur.__context__
    haystack = " ".join(blobs).lower()
    for selector, name in _error_selectors().items():
        if selector in haystack:
            return name
    return None


@dataclass(frozen=True, slots=True)
class Receipt:
    success: bool
    block_number: int
    block_timestamp: int
    confirmations: int


class AnchorChain(Protocol):
    chain_id: int
    contract_address: str

    async def submit(self, root: bytes, leaf_count: int) -> str: ...
    async def receipt(self, tx_hash: str) -> Receipt | None: ...
    async def anchored_at(self, root: bytes) -> int: ...


class EvmChain:
    def __init__(self, w3: Any, contract_address: str, private_key: str) -> None:
        from eth_account import Account

        self.w3 = w3
        self.account = Account.from_key(private_key)
        self.contract_address = w3.to_checksum_address(contract_address)
        self.contract = w3.eth.contract(address=self.contract_address, abi=artifact()["abi"])
        self.chain_id = int(w3.eth.chain_id)
        self._lock = asyncio.Lock()  # one relayer => serialise nonces

    def _submit(self, root: bytes, leaf_count: int) -> str:
        tx = self.contract.functions.anchor(root, leaf_count).build_transaction(
            {
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address, "pending"),
                "chainId": self.chain_id,
            }
        )
        signed = self.account.sign_transaction(tx)
        return str(self.w3.eth.send_raw_transaction(signed.raw_transaction).to_0x_hex())

    async def submit(self, root: bytes, leaf_count: int) -> str:
        async with self._lock:
            try:
                return await asyncio.to_thread(self._submit, root, leaf_count)
            except Exception as e:
                name = decode_revert(e)
                if name is None:
                    raise
                raise AnchorRejected(
                    f"Contract rejected anchor: {name}", code="anchor_rejected", details={"error": name}
                ) from e

    def _receipt(self, tx_hash: str) -> Receipt | None:
        from web3.exceptions import TransactionNotFound

        try:
            r = self.w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None
        if r is None:
            return None
        block = self.w3.eth.get_block(r["blockNumber"])
        head = self.w3.eth.block_number
        return Receipt(
            success=r["status"] == 1,
            block_number=int(r["blockNumber"]),
            block_timestamp=int(block["timestamp"]),
            confirmations=int(head - r["blockNumber"] + 1),
        )

    async def receipt(self, tx_hash: str) -> Receipt | None:
        return await asyncio.to_thread(self._receipt, tx_hash)

    async def anchored_at(self, root: bytes) -> int:
        return int(await asyncio.to_thread(self.contract.functions.anchoredAt(root).call))


def deploy(w3: Any, private_key: str) -> str:
    """Deploy LexLabAnchor; the deployer becomes the only allowed relayer."""
    from eth_account import Account

    acct = Account.from_key(private_key)
    art = artifact()
    factory = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    tx = factory.constructor().build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
            "chainId": w3.eth.chain_id,
        }
    )
    tx_hash = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    return str(receipt["contractAddress"])


_override: AnchorChain | None = None


def set_chain(chain: AnchorChain | None) -> None:
    """Test hook / custom backends (e.g. a Hyperledger Fabric adapter implementing AnchorChain)."""
    global _override
    _override = chain
    _default_chain.cache_clear()


@lru_cache
def _default_chain() -> AnchorChain:
    from web3 import Web3

    s = get_settings()
    if not (s.evm_rpc_url and s.anchor_contract_address and s.relayer_private_key):
        raise IntegrationUnavailable(
            "Anchoring needs EVM_RPC_URL, ANCHOR_CONTRACT_ADDRESS and RELAYER_PRIVATE_KEY", code="anchor_unavailable"
        )
    w3 = Web3(Web3.HTTPProvider(s.evm_rpc_url, request_kwargs={"timeout": 20}))
    chain = EvmChain(w3, s.anchor_contract_address, s.relayer_private_key)
    if chain.chain_id != s.evm_chain_id:
        raise IntegrationUnavailable(
            f"RPC chain id {chain.chain_id} != configured {s.evm_chain_id}", code="anchor_wrong_chain"
        )
    return chain


def get_chain() -> AnchorChain:
    return _override if _override is not None else _default_chain()
