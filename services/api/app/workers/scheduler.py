"""Periodic jobs shared by the in-process loop and the ARQ worker."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import update

from app.core.config import get_settings
from app.core.timeutils import today_local
from app.db.session import session_scope
from app.modules.anchoring.service import run_cycle as anchor_cycle
from app.modules.contracts.models import Contract, ContractStatus
from app.modules.reminders.service import run_dispatch_cycle
from app.modules.templates.service import check_sources

log = logging.getLogger(__name__)


async def tick() -> dict[str, int]:
    """Every minute: dispatch due reminders, flag overdue obligations."""
    async with session_scope() as db:
        stats = await run_dispatch_cycle(db)
    if stats["claimed"] or stats["overdue"]:
        log.info("scheduler_tick", extra=stats)
    try:  # anchoring is isolated: an RPC outage must never block reminders
        async with session_scope() as db:
            anchored = await anchor_cycle(db)
        if anchored.get("built") or anchored.get("submitted") or anchored.get("confirmed"):
            log.info("anchor_tick", extra=anchored)
    except Exception:
        log.exception("anchor_tick_failed")
    return stats


async def daily() -> None:
    """Once a day: move active contracts past their end date to «Muddati tugagan»."""
    today = today_local()
    async with session_scope() as db:
        await db.execute(
            update(Contract)
            .where(Contract.status == ContractStatus.ACTIVE, Contract.ends_on < today)
            .values(status=ContractStatus.EXPIRED)
        )
    try:  # lex.uz monitoring is isolated: a network problem must not break the daily job
        async with session_scope() as db:
            res = await check_sources(db)
        if res["changed"] or res["lost_force"]:
            log.warning("lexuz_sources_changed", extra=res)
    except Exception:
        log.exception("lexuz_check_failed")


async def run_forever(stop: asyncio.Event) -> None:
    interval = get_settings().scheduler_interval_seconds
    last_daily = None
    while not stop.is_set():
        try:
            await tick()
            if last_daily != today_local():
                await daily()
                last_daily = today_local()
        except Exception:
            log.exception("scheduler_error")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
