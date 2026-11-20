"""Prepare the Vercel demo deployment.

1. services/api/.env.vercel  — fresh JWT secret + master encryption key (created once, gitignored).
2. services/api/vercel/seed.db — SQLite snapshot: migrations + contract types, clauses, rules, reference data
   and ONE demo user (the verified lawyer). Admin/editor/moderator demo users are deliberately left out:
   the public demo uses a fixed SMS code, so privileged accounts must not exist there.

    services\\api\\.venv\\Scripts\\python scripts\\build_vercel_db.py
"""

from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
ENV_FILE = API / ".env.vercel"
DB = API / "vercel" / "seed.db"
PY = API / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def secrets_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        ENV_FILE.write_text(
            f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
            f"MASTER_ENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}\n",
            encoding="utf-8",
        )
    out = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "DATABASE_URL"))}
    env.update(secrets_env())
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    env.update(
        {
            "ENVIRONMENT": "dev",
            "DATABASE_URL": f"sqlite+aiosqlite:///{DB.as_posix()}",
            "LEGAL_CONTENT_DIR": str(ROOT / "packages" / "legal-content"),
            "SCHEDULER_MODE": "off",
            "LLM_PROVIDER": "none",
        }
    )
    subprocess.run([str(PY), "-m", "alembic", "upgrade", "head"], cwd=API, env=env, check=True)
    seed = (
        "import sys, app.seed as s\n"
        "s.DEV_USERS = [u for u in s.DEV_USERS if u[1].value == 'lawyer']\n"
        "sys.argv = ['seed', '--dev-users']\n"
        "s.main()\n"
    )
    subprocess.run([str(PY), "-c", seed], cwd=API, env=env, check=True)
    print(f"seed db: {DB} ({DB.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
