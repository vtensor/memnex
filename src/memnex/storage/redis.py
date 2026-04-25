"""Redis hot store. Lazy-imported to keep redis an optional dependency."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from memnex.memory.models import Memory

if TYPE_CHECKING:
    import redis.asyncio as aioredis


class RedisHotStore:
    def __init__(self, client: "aioredis.Redis") -> None:
        self._r = client

    @classmethod
    async def create(cls, url: str) -> "RedisHotStore":
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            raise ImportError(
                "redis not installed. `pip install memnex[redis]`."
            ) from e
        client = aioredis.from_url(url, decode_responses=True)
        return cls(client)

    @staticmethod
    def _wm_key(tenant_id: str, customer_id: str) -> str:
        return f"memnex:{tenant_id}:{customer_id}:working_memory"

    @staticmethod
    def _id_key(tenant_id: str, channel: str, identifier: str) -> str:
        return f"memnex:{tenant_id}:id:{channel}:{identifier}"

    async def get_working_memory(self, tenant_id: str, customer_id: str) -> list[Memory] | None:
        raw = await self._r.get(self._wm_key(tenant_id, customer_id))
        if not raw:
            return None
        data = json.loads(raw)
        return [Memory.model_validate(x) for x in data]

    async def set_working_memory(
        self, tenant_id: str, customer_id: str, memories: list[Memory], ttl_seconds: int
    ) -> None:
        raw = json.dumps([m.model_dump(mode="json") for m in memories])
        await self._r.set(self._wm_key(tenant_id, customer_id), raw, ex=ttl_seconds)

    async def invalidate(self, tenant_id: str, customer_id: str) -> None:
        await self._r.delete(self._wm_key(tenant_id, customer_id))

    async def get_identifier_cache(
        self, tenant_id: str, channel: str, identifier: str
    ) -> str | None:
        return await self._r.get(self._id_key(tenant_id, channel, identifier))

    async def set_identifier_cache(
        self, tenant_id: str, channel: str, identifier: str, customer_id: str, ttl_seconds: int
    ) -> None:
        await self._r.set(
            self._id_key(tenant_id, channel, identifier), customer_id, ex=ttl_seconds
        )

    async def close(self) -> None:
        await self._r.aclose()
