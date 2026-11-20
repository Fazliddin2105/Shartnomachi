"""Fixed-window rate limiter: Redis when configured, in-memory otherwise."""

from __future__ import annotations

import time
from collections import defaultdict
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import RateLimited


class Limiter(Protocol):
    async def hit(self, key: str, limit: int, window_s: int) -> None: ...


class MemoryLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    async def hit(self, key: str, limit: int, window_s: int) -> None:
        window = int(time.time() // window_s)
        w, count = self._buckets[key]
        count = count + 1 if w == window else 1
        self._buckets[key] = (window, count)
        if count > limit:
            raise RateLimited(details={"retry_after_s": window_s})

    def reset(self) -> None:
        self._buckets.clear()


class RedisLimiter:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._r = Redis.from_url(url)

    async def hit(self, key: str, limit: int, window_s: int) -> None:
        k = f"rl:{key}:{int(time.time() // window_s)}"
        count = await self._r.incr(k)
        if count == 1:
            await self._r.expire(k, window_s)
        if count > limit:
            raise RateLimited(details={"retry_after_s": window_s})


@lru_cache
def get_limiter() -> Limiter:
    url = get_settings().redis_url
    return RedisLimiter(url) if url else MemoryLimiter()
