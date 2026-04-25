"""Cache invalidation pub/sub bus.

On every write, publishes ``(tenant_id, user_id, version)``. Every Memnex
instance subscribes and drops its working-memory cache for that user.

In-process bus: asyncio broadcast.
Redis bus: PUBSUB on channel ``memnex:invalidate``.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

Handler = Callable[[str, str, int], Awaitable[None]]  # (tenant_id, user_id, version)


class InvalidationBus(Protocol):
    async def publish(self, tenant_id: str, user_id: str, version: int) -> None: ...
    async def subscribe(self, handler: Handler) -> None: ...
    async def close(self) -> None: ...


class InProcessBus:
    """In-memory bus. All subscribers in the same process see every publish."""

    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        self._published: int = 0

    async def publish(self, tenant_id: str, user_id: str, version: int) -> None:
        self._published += 1
        await asyncio.gather(
            *(h(tenant_id, user_id, version) for h in self._handlers),
            return_exceptions=True,
        )

    async def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def close(self) -> None:
        self._handlers.clear()

    @property
    def publish_count(self) -> int:
        return self._published


class RedisBus:
    """Redis pub/sub bus. Works across processes and machines."""

    CHANNEL = "memnex:invalidate"

    def __init__(self, client) -> None:
        self._r = client
        self._task: asyncio.Task | None = None
        self._handlers: list[Handler] = []

    async def publish(self, tenant_id: str, user_id: str, version: int) -> None:
        payload = json.dumps(
            {"tenant": tenant_id, "user": user_id, "version": version}
        )
        await self._r.publish(self.CHANNEL, payload)

    async def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)
        if self._task is None:
            self._task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        pubsub = self._r.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            data = json.loads(msg["data"])
            for h in self._handlers:
                try:
                    await h(data["tenant"], data["user"], int(data["version"]))
                except Exception:
                    pass

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._handlers.clear()
