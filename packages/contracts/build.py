"""Compile LexLabAnchor.sol -> build/LexLabAnchor.json (ABI + bytecode).

    python packages/contracts/build.py        (needs: pip install py-solc-x)

The JSON artifact is committed, so servers never need a Solidity compiler.
evmVersion "paris" keeps the bytecode free of PUSH0 for maximum EVM-chain compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path

import solcx

SOLC = "0.8.24"
HERE = Path(__file__).resolve().parent


def main() -> None:
    solcx.install_solc(SOLC)
    out = solcx.compile_standard(
        {
            "language": "Solidity",
            "sources": {"LexLabAnchor.sol": {"content": (HERE / "LexLabAnchor.sol").read_text(encoding="utf-8")}},
            "settings": {
                "optimizer": {"enabled": True, "runs": 200},
                "evmVersion": "paris",
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        },
        solc_version=SOLC,
    )
    c = out["contracts"]["LexLabAnchor.sol"]["LexLabAnchor"]
    artifact = {
        "contractName": "LexLabAnchor",
        "compiler": f"solc {SOLC}",
        "optimizer_runs": 200,
        "evmVersion": "paris",
        "abi": c["abi"],
        "bytecode": "0x" + c["evm"]["bytecode"]["object"],
    }
    (HERE / "build").mkdir(exist_ok=True)
    (HERE / "build" / "LexLabAnchor.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"ok: {len(c['evm']['bytecode']['object']) // 2} bytes")


if __name__ == "__main__":
    main()
