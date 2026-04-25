"""Pick storage backends + concurrency primitives based on config.

If ``MEMNEX_POSTGRES_URL`` / ``MEMNEX_REDIS_URL`` / ``MEMNEX_QDRANT_URL`` are
set, use real backends; otherwise use in-memory. This keeps tests and local
demos zero-dependency, and makes a multi-instance deployment "just work"
when the env vars are set: the Redis-backed bus + version clock use the
same Redis client the hot store uses, so a write on instance A fans out to
every other instance via Redis PUBSUB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from memnex.concurrency.bus import InProcessBus, InvalidationBus, RedisBus
from memnex.concurrency.versions import (
    InProcessVersionClock,
    RedisVersionClock,
    VersionClock,
)
from memnex.config import MemnexConfig
from memnex.storage.base import HotStore, SemanticStore, WarmStore
from memnex.storage.memory_backend import (
    InMemoryHotStore,
    InMemorySemanticStore,
    InMemoryWarmStore,
)

if TYPE_CHECKING:
    pass


@dataclass
class Stores:
    hot: HotStore
    warm: WarmStore
    semantic: SemanticStore
    versions: VersionClock = field(default_factory=InProcessVersionClock)
    bus: InvalidationBus = field(default_factory=InProcessBus)

    async def close(self) -> None:
        await self.hot.close()
        await self.warm.close()
        await self.semantic.close()
        await self.bus.close()


async def open_stores(config: MemnexConfig) -> Stores:
    hot: HotStore
    warm: WarmStore
    semantic: SemanticStore
    versions: VersionClock
    bus: InvalidationBus

    if config.redis_url:
        # Multi-instance mode: share a single Redis client for hot store +
        # version clock + pub/sub. One TCP pool, three features.
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            raise ImportError(
                "redis not installed. `pip install memnex[redis]`."
            ) from e
        redis_client = aioredis.from_url(config.redis_url, decode_responses=True)

        from memnex.storage.redis import RedisHotStore
        hot = RedisHotStore(redis_client)
        versions = RedisVersionClock(redis_client)
        bus = RedisBus(redis_client)
    else:
        hot = InMemoryHotStore()
        versions = InProcessVersionClock()
        bus = InProcessBus()

    if config.postgres_url:
        from memnex.storage.postgres import PostgresWarmStore
        warm = await PostgresWarmStore.create(config.postgres_url)
    else:
        warm = InMemoryWarmStore()

    if config.qdrant_url:
        from memnex.storage.qdrant import QdrantSemanticStore
        semantic = QdrantSemanticStore(config.qdrant_url, config.embedding_dimensions)
    else:
        semantic = InMemorySemanticStore()

    return Stores(
        hot=hot, warm=warm, semantic=semantic, versions=versions, bus=bus,
    )
