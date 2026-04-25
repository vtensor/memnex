"""Storage protocols.

The library operates on these interfaces; concrete backends (Postgres, Redis,
Qdrant, or in-memory) implement them. This is what makes Memnex testable
without Docker and swappable across deployments.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from memnex.identity.models import CandidateLink, ChannelIdentifier, Customer
from memnex.memory.models import Memory


class HotStore(Protocol):
    """Short-lived, fast access (Redis / in-memory)."""

    async def get_working_memory(self, tenant_id: str, customer_id: str) -> list[Memory] | None: ...
    async def set_working_memory(
        self, tenant_id: str, customer_id: str, memories: list[Memory], ttl_seconds: int
    ) -> None: ...
    async def invalidate(self, tenant_id: str, customer_id: str) -> None: ...
    async def get_identifier_cache(
        self, tenant_id: str, channel: str, identifier: str
    ) -> str | None: ...
    async def set_identifier_cache(
        self, tenant_id: str, channel: str, identifier: str, customer_id: str, ttl_seconds: int
    ) -> None: ...
    async def close(self) -> None: ...


class WarmStore(Protocol):
    """Durable, tenant-scoped storage (Postgres / in-memory)."""

    # --- identity ---
    async def upsert_customer(self, customer: Customer) -> None: ...
    async def get_customer(self, tenant_id: str, customer_id: str) -> Customer | None: ...
    async def find_by_identifier(
        self, tenant_id: str, channel: str, identifier: str
    ) -> Customer | None: ...
    async def add_identifier(self, identifier: ChannelIdentifier) -> None: ...
    async def list_identifiers(
        self, tenant_id: str, customer_id: str
    ) -> list[ChannelIdentifier]: ...
    async def record_candidate_link(self, link: CandidateLink) -> None: ...
    async def list_candidate_links(
        self, tenant_id: str, customer_id: str
    ) -> list[CandidateLink]: ...

    # --- memories ---
    async def insert_memory(self, memory: Memory) -> None: ...
    async def supersede_memory(
        self, tenant_id: str, memory_id: str, superseded_by: str
    ) -> None: ...
    async def get_memories_by_ids(
        self, tenant_id: str, customer_id: str, ids: list[str]
    ) -> list[Memory]: ...
    async def list_memories(
        self,
        tenant_id: str,
        customer_id: str,
        *,
        limit: int = 50,
        active_only: bool = True,
        fact_type: str | None = None,
    ) -> list[Memory]: ...
    async def list_expired(self, now: datetime) -> list[Memory]: ...

    # --- admin / privacy ---
    async def delete_customer(self, tenant_id: str, customer_id: str) -> dict[str, int]: ...
    async def tenant_stats(self, tenant_id: str) -> dict[str, Any]: ...
    async def close(self) -> None: ...


class SemanticStore(Protocol):
    """Vector search (Qdrant / in-memory)."""

    async def upsert(
        self,
        tenant_id: str,
        customer_id: str,
        memory_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> str: ...
    async def search(
        self,
        tenant_id: str,
        customer_id: str,
        embedding: list[float],
        *,
        limit: int = 5,
    ) -> list[tuple[str, float]]:
        """Return list of (memory_id, score)."""
        ...

    async def delete_customer(self, tenant_id: str, customer_id: str) -> int: ...
    async def close(self) -> None: ...
