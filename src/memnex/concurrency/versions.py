"""Per-user monotonic version counter.

Lets readers assert: "I want to see at least version N of this user's
memory." Combined with the invalidation bus, this gives us read-after-write
consistency across instances.

Backends:
- In-process: asyncio.Lock around a dict. Single-process only.
- Redis: INCR on a per-user key. Multi-process safe.
"""
from __future__ import annotations

import asyncio
from typing import Protocol


class VersionClock(Protocol):
    async def bump(self, tenant_id: str, user_id: str) -> int: ...
    async def current(self, tenant_id: str, user_id: str) -> int: ...


class InProcessVersionClock:
    def __init__(self) -> None:
        self._v: dict[tuple[str, str], int] = {}
        self._lock = asyncio.Lock()

    async def bump(self, tenant_id: str, user_id: str) -> int:
        async with self._lock:
            nv = self._v.get((tenant_id, user_id), 0) + 1
            self._v[(tenant_id, user_id)] = nv
            return nv

    async def current(self, tenant_id: str, user_id: str) -> int:
        return self._v.get((tenant_id, user_id), 0)


class RedisVersionClock:
    def __init__(self, client) -> None:
        self._r = client

    @staticmethod
    def _key(tenant_id: str, user_id: str) -> str:
        return f"memnex:{tenant_id}:{user_id}:version"

    async def bump(self, tenant_id: str, user_id: str) -> int:
        return int(await self._r.incr(self._key(tenant_id, user_id)))

    async def current(self, tenant_id: str, user_id: str) -> int:
        raw = await self._r.get(self._key(tenant_id, user_id))
        return int(raw) if raw else 0
