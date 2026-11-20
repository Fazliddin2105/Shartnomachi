"""Vercel entry point: the LexLab API, the web app and the SDK as one Python function.

Vercel has no persistent disk. For the hackathon demo the database is SQLite in /tmp, restored from a
pre-seeded snapshot (contract types, rules, demo lawyer) whenever a fresh instance starts; uploaded and
generated files also live in /tmp (signed DOCX files are rebuilt from the stored content if missing).
For production use Postgres + S3 (DATABASE_URL / STORAGE_BACKEND) — see docs/deploy-vercel.md.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

TMP = Path(os.environ.get("LEXLAB_TMP", "/tmp/lexlab"))
TMP.mkdir(parents=True, exist_ok=True)
_db = TMP / "lexlab.db"
if os.environ.get("DATABASE_URL_UNPOOLED"):
    # Neon (Vercel Marketplace): direct connection + a small pool per instance; the asyncpg URL form is
    # derived from it by Settings (postgres://…?sslmode=require -> postgresql+asyncpg://…?ssl=require).
    os.environ["DATABASE_URL"] = os.environ["DATABASE_URL_UNPOOLED"]
    os.environ.setdefault("DB_POOL_SIZE", "2")
    os.environ.setdefault("DB_MAX_OVERFLOW", "3")
    os.environ.setdefault("DB_POOL_RECYCLE_SECONDS", "240")
elif not os.environ.get("DATABASE_URL"):
    if not _db.exists():
        shutil.copyfile(API_DIR / "vercel" / "seed.db", _db)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db.as_posix()}"

os.environ.setdefault("STORAGE_LOCAL_ROOT", str(TMP / "storage"))
os.environ.setdefault("LEGAL_CONTENT_DIR", str(ROOT / "packages" / "legal-content"))
os.environ.setdefault("FRONTEND_DIR", str(ROOT / "apps" / "web"))
os.environ.setdefault("INLINE_JOBS", "true")  # the instance may be frozen right after a response
os.environ.setdefault("SCHEDULER_MODE", "off")  # no long-running loop on serverless

from app.main import app  # noqa: E402

__all__ = ["app"]
