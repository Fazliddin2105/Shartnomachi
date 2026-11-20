"""Run migrations + seed on the Vercel project's Postgres (Neon). The connection URL is fetched from the
project's environment through the Vercel API and never printed.

    services\\api\\.venv\\Scripts\\python scripts\\vercel_migrate.py <file-with-vercel-token> [project-name]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
PY = API / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
sys.path.insert(0, str(ROOT / "scripts"))
from build_vercel_db import secrets_env  # noqa: E402


def project_env(token: str, project: str, key: str) -> str:
    c = httpx.Client(base_url="https://api.vercel.com", headers={"Authorization": f"Bearer {token}"}, timeout=60)
    pid = c.get(f"/v9/projects/{project}").json()["id"]
    envs = c.get(f"/v9/projects/{pid}/env").json()["envs"]
    match = [e for e in envs if e["key"] == key and "production" in (e.get("target") or [])]
    if not match:
        raise SystemExit(f"{key} is not set on the project")
    value = c.get(f"/v1/projects/{pid}/env/{match[0]['id']}").json().get("value")
    if not value or not value.startswith("postgres"):
        raise SystemExit(f"{key} could not be read (type={match[0].get('type')})")
    return value


def main() -> None:
    token = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    project = sys.argv[2] if len(sys.argv) > 2 else "lexlab-platform"
    url = project_env(token, project, "DATABASE_URL_UNPOOLED")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "DATABASE_URL"))}
    env.update(secrets_env())
    env.update({
        "ENVIRONMENT": "dev",
        "DATABASE_URL": url,
        "LEGAL_CONTENT_DIR": str(ROOT / "packages" / "legal-content"),
        "SCHEDULER_MODE": "off",
        "LLM_PROVIDER": "none",
    })
    subprocess.run([str(PY), "-m", "alembic", "upgrade", "head"], cwd=API, env=env, check=True)
    seed = (
        "import sys, app.seed as s\n"
        "s.DEV_USERS = [u for u in s.DEV_USERS if u[1].value == 'lawyer']\n"
        "sys.argv = ['seed', '--dev-users']\n"
        "s.main()\n"
    )
    out = subprocess.run([str(PY), "-c", seed], cwd=API, env=env, check=True, capture_output=True, text=True)
    print("seed:", json.loads(out.stdout.strip().splitlines()[-1]))


if __name__ == "__main__":
    main()
