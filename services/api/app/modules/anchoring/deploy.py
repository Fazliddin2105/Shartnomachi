"""Relayer wallet + contract deployment CLI.

python -m app.modules.anchoring.deploy --new-key     # create a relayer wallet (fund it from the Amoy faucet)
python -m app.modules.anchoring.deploy               # deploy LexLabAnchor with RELAYER_PRIVATE_KEY to EVM_RPC_URL
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-key", action="store_true", help="generate a relayer wallet and exit")
    args = parser.parse_args()

    from eth_account import Account

    if args.new_key:
        acct = Account.create()
        print(f"RELAYER_ADDRESS={acct.address}")
        print(f"RELAYER_PRIVATE_KEY={acct.key.hex()}")
        print("Fund the address with test POL (Polygon Amoy faucet), keep the key in a secret store, never in git.")
        return

    from web3 import Web3

    from app.modules.anchoring.chain import deploy

    s = get_settings()
    if not (s.evm_rpc_url and s.relayer_private_key):
        raise SystemExit("Set EVM_RPC_URL and RELAYER_PRIVATE_KEY first")
    w3 = Web3(Web3.HTTPProvider(s.evm_rpc_url, request_kwargs={"timeout": 30}))
    if w3.eth.chain_id != s.evm_chain_id:
        raise SystemExit(f"RPC chain id {w3.eth.chain_id} != EVM_CHAIN_ID {s.evm_chain_id}")
    address = deploy(w3, s.relayer_private_key)
    print(f"ANCHOR_CONTRACT_ADDRESS={address}")
    print(s.anchor_explorer_tx_url.replace("/tx/{tx}", f"/address/{address}"))


if __name__ == "__main__":
    main()
