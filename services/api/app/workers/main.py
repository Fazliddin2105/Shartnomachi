"""ARQ worker: `python -m arq app.workers.main.WorkerSettings` (or `python -m app.workers.main`).

Runs OCR/scan analysis, case exports and the reminder scheduler (cron, every
minute). Several replicas are safe: reminder claiming uses SKIP LOCKED.
"""

from __future__ import annotations

import uuid
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine, init_engine
from app.workers import scheduler


async def process_scan(ctx: dict[str, Any], job_id: str) -> None:
    from app.modules.scan.service import process

    await process(uuid.UUID(job_id))


async def build_case_export(ctx: dict[str, Any], case_id: str, user_id: str) -> None:
    from app.modules.cases.service import build_export_job

    await build_export_job(case_id, user_id)


async def ai_review_scan(ctx: dict[str, Any], job_id: str) -> None:
    from app.modules.scan.service import ai_review

    await ai_review(uuid.UUID(job_id))


async def reminders_tick(ctx: dict[str, Any]) -> None:
    await scheduler.tick()


async def daily_maintenance(ctx: dict[str, Any]) -> None:
    await scheduler.daily()


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    init_engine()


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()


class WorkerSettings:
    functions = [process_scan, build_case_export, ai_review_scan]
    cron_jobs = [
        cron(reminders_tick, second=0),  # every minute
        cron(daily_maintenance, hour=0, minute=5),  # UTC 00:05 = 05:05 Tashkent
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 10
    job_timeout = 600


if __name__ == "__main__":
    from arq import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]
