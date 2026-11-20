"""Create/link the Vercel project and set its environment variables (values are never printed).

    services\\api\\.venv\\Scripts\\python scripts\\vercel_setup.py <path-to-file-with-vercel-token> [project-name]

Reads secrets from services/api/.env.vercel (JWT/master key) and the LLM settings from services/api/.env.
Writes .vercel/project.json so `vercel deploy` targets this project.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split(" #", 1)[0].strip()
    return out


def main() -> None:
    token = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    name = sys.argv[2] if len(sys.argv) > 2 else "lexlab-platform"
    c = httpx.Client(base_url="https://api.vercel.com", headers={"Authorization": f"Bearer {token}"}, timeout=60)

    user = c.get("/v2/user").json()["user"]
    r = c.get(f"/v9/projects/{name}")
    if r.status_code == 404:
        r = c.post("/v11/projects", json={"name": name, "framework": None})
        r.raise_for_status()
        print("project created:", name)
    else:
        r.raise_for_status()
        print("project exists:", name)
    project = r.json()

    secrets_ = read_env(API / ".env.vercel")
    local = read_env(API / ".env")
    env = {
        "ENVIRONMENT": "dev",  # hackathon demo: fixed SMS code + external LLM are allowed only in dev
        "OTP_DEV_FIXED_CODE": "111111",
        "OTP_HOURLY_LIMIT": "100",
        "OTP_IP_HOURLY_LIMIT": "1000",
        "OTP_RESEND_COOLDOWN_SECONDS": "15",
        "JWT_SECRET": secrets_["JWT_SECRET"],
        "MASTER_ENCRYPTION_KEY": secrets_["MASTER_ENCRYPTION_KEY"],
        "SCHEDULER_MODE": "off",
        "INLINE_JOBS": "true",
        "LOG_JSON": "true",
    }
    for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_IS_LOCAL", "LLM_API_KEY"):
        if local.get(k):
            env[k] = local[k]
    sensitive = {"JWT_SECRET", "MASTER_ENCRYPTION_KEY", "LLM_API_KEY"}
    body = [
        {"key": k, "value": v, "type": "encrypted" if k in sensitive else "plain", "target": ["production", "preview"]}
        for k, v in env.items()
    ]
    r = c.post(f"/v10/projects/{project['id']}/env", params={"upsert": "true"}, json=body)
    if r.is_error:
        raise SystemExit(f"env update failed: {r.status_code} {r.json().get('error', {}).get('message')}")
    print("env vars set:", sorted(env))  # names only

    link = ROOT / ".vercel" / "project.json"
    link.parent.mkdir(exist_ok=True)
    link.write_text(json.dumps({"projectId": project["id"], "orgId": project.get("accountId") or user["id"]}), "utf-8")
    print("linked:", link)


if __name__ == "__main__":
    main()
