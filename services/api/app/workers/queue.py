"""Task dispatch abstraction.

* `worker` mode: jobs go to Redis and are executed by the ARQ worker
  (`python -m app.workers.main`) — horizontally scalable, survives restarts.
* otherwise: jobs run as tracked asyncio tasks inside the API process
  (dev / tests). `drain()` awaits them (used by tests and graceful shutdown).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import SchedulerMode, get_settings

log = logging.getLogger(__name__)

_tasks: set[asyncio.Task[Any]] = set()
_pool: Any = None


def _registry() -> dict[str, Callable[..., Awaitable[Any]]]:
    from app.modules.cases.service import build_export_job
    from app.modules.scan.service import ai_review as ai_review_scan
    from app.modules.scan.service import process as process_scan

    return {"process_scan": process_scan, "build_case_export": build_export_job, "ai_review_scan": ai_review_scan}


async def _arq_pool() -> Any:
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379"))
    return _pool


async def enqueue(name: str, *args: Any) -> None:
    s = get_settings()
    if s.scheduler_mode == SchedulerMode.WORKER and s.redis_url:
        pool = await _arq_pool()
        await pool.enqueue_job(name, *[str(a) if isinstance(a, uuid.UUID) else a for a in args])
        return
    fn = _registry()[name]

    if s.inline_jobs:
        # Serverless (e.g. Vercel): the process may be frozen right after the response, so the job runs
        # inside the request. Callers commit before enqueueing, so the job's own session sees the data.
        try:
            await fn(*args)
        except Exception:
            log.exception("inline_task_failed", extra={"task": name})
        return

    async def _run() -> None:
        try:
            await fn(*args)
        except Exception:
            log.exception("background_task_failed", extra={"task": name})

    task = asyncio.create_task(_run(), name=f"bg:{name}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain(timeout: float = 30) -> None:
    if _tasks:
        await asyncio.wait(set(_tasks), timeout=timeout)
