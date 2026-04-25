"""In-process per-tenant rate limiter.

A sliding window over the last minute. For multi-process deployments replace
with a Redis-backed limiter — interface stays the same.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, rpm: int = 600) -> None:
        self._rpm = rpm
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    async def check(self, tenant: str) -> None:
        now = time.monotonic()
        window = self._windows[tenant]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._rpm:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        window.append(now)


_limiter = RateLimiter()


async def rate_limit(request: Request) -> None:
    tenant = request.app.state.memnex.config.tenant_id
    await _limiter.check(tenant)
