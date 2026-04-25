"""Qdrant semantic store. One collection per tenant gives the strongest isolation."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient


class QdrantSemanticStore:
    def __init__(self, url: str, embedding_dim: int) -> None:
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as e:
            raise ImportError(
                "qdrant-client not installed. `pip install memnex[qdrant]`."
            ) from e
        self._client: "AsyncQdrantClient" = AsyncQdrantClient(url=url)
        self._dim = embedding_dim
        self._ensured: set[str] = set()

    def _collection(self, tenant_id: str) -> str:
        return f"memnex_{tenant_id}".replace("-", "_")

    async def _ensure_collection(self, tenant_id: str) -> str:
        name = self._collection(tenant_id)
        if name in self._ensured:
            return name
        from qdrant_client.http import models as rest
        existing = await self._client.get_collections()
        if not any(c.name == name for c in existing.collections):
            await self._client.create_collection(
                collection_name=name,
                vectors_config=rest.VectorParams(
                    size=self._dim, distance=rest.Distance.COSINE
                ),
            )
        self._ensured.add(name)
        return name

    async def upsert(
        self,
        tenant_id: str,
        customer_id: str,
        memory_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> str:
        from qdrant_client.http import models as rest
        coll = await self._ensure_collection(tenant_id)
        await self._client.upsert(
            collection_name=coll,
            points=[
                rest.PointStruct(
                    id=memory_id,
                    vector=embedding,
                    payload={"customer_id": customer_id, "text": text, **metadata},
                )
            ],
        )
        return memory_id

    async def search(
        self,
        tenant_id: str,
        customer_id: str,
        embedding: list[float],
        *,
        limit: int = 5,
    ) -> list[tuple[str, float]]:
        from qdrant_client.http import models as rest
        coll = await self._ensure_collection(tenant_id)
        results = await self._client.search(
            collection_name=coll,
            query_vector=embedding,
            query_filter=rest.Filter(
                must=[rest.FieldCondition(key="customer_id", match=rest.MatchValue(value=customer_id))]
            ),
            limit=limit,
        )
        return [(str(r.id), float(r.score)) for r in results]

    async def delete_customer(self, tenant_id: str, customer_id: str) -> int:
        from qdrant_client.http import models as rest
        coll = await self._ensure_collection(tenant_id)
        resp = await self._client.delete(
            collection_name=coll,
            points_selector=rest.FilterSelector(
                filter=rest.Filter(
                    must=[rest.FieldCondition(key="customer_id", match=rest.MatchValue(value=customer_id))]
                )
            ),
        )
        return int(getattr(resp, "operation_id", 0) or 0)

    async def close(self) -> None:
        await self._client.close()
