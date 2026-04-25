"""In-memory storage. Default backend when no URLs are configured.

Intended for tests, local demos, and CI. Data is not persisted across processes.
Tenant isolation is enforced here the same way it is in Postgres — every query
is scoped by ``tenant_id`` and data lives in per-tenant dicts.
"""
from __future__ import annotations

from memnex._time import utcnow

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from memnex.identity.models import CandidateLink, ChannelIdentifier, Customer
from memnex.memory.models import Memory


class InMemoryHotStore:
    def __init__(self) -> None:
        self._working: dict[tuple[str, str], tuple[list[Memory], datetime]] = {}
        self._id_cache: dict[tuple[str, str, str], tuple[str, datetime]] = {}

    async def get_working_memory(self, tenant_id: str, customer_id: str) -> list[Memory] | None:
        entry = self._working.get((tenant_id, customer_id))
        if not entry:
            return None
        memories, expires = entry
        if utcnow() > expires:
            self._working.pop((tenant_id, customer_id), None)
            return None
        return list(memories)

    async def set_working_memory(
        self, tenant_id: str, customer_id: str, memories: list[Memory], ttl_seconds: int
    ) -> None:
        from datetime import timedelta
        self._working[(tenant_id, customer_id)] = (
            list(memories),
            utcnow() + timedelta(seconds=ttl_seconds),
        )

    async def invalidate(self, tenant_id: str, customer_id: str) -> None:
        self._working.pop((tenant_id, customer_id), None)

    async def get_identifier_cache(
        self, tenant_id: str, channel: str, identifier: str
    ) -> str | None:
        entry = self._id_cache.get((tenant_id, channel, identifier))
        if not entry:
            return None
        customer_id, expires = entry
        if utcnow() > expires:
            self._id_cache.pop((tenant_id, channel, identifier), None)
            return None
        return customer_id

    async def set_identifier_cache(
        self, tenant_id: str, channel: str, identifier: str, customer_id: str, ttl_seconds: int
    ) -> None:
        from datetime import timedelta
        self._id_cache[(tenant_id, channel, identifier)] = (
            customer_id,
            utcnow() + timedelta(seconds=ttl_seconds),
        )

    async def close(self) -> None:
        self._working.clear()
        self._id_cache.clear()


class InMemoryWarmStore:
    def __init__(self) -> None:
        self._customers: dict[tuple[str, str], Customer] = {}
        self._identifiers: dict[tuple[str, str, str], ChannelIdentifier] = {}
        self._memories: dict[str, Memory] = {}
        self._candidate_links: dict[str, CandidateLink] = {}

    # --- identity ---
    async def upsert_customer(self, customer: Customer) -> None:
        self._customers[(customer.tenant_id, customer.id)] = customer

    async def get_customer(self, tenant_id: str, customer_id: str) -> Customer | None:
        return self._customers.get((tenant_id, customer_id))

    async def find_by_identifier(
        self, tenant_id: str, channel: str, identifier: str
    ) -> Customer | None:
        key = (tenant_id, channel, identifier)
        ident = self._identifiers.get(key)
        if not ident:
            return None
        return self._customers.get((tenant_id, ident.customer_id))

    async def add_identifier(self, identifier: ChannelIdentifier) -> None:
        customer = self._customers.get((
            self._tenant_of(identifier.customer_id),
            identifier.customer_id,
        ))
        tenant_id = customer.tenant_id if customer else self._tenant_of(identifier.customer_id)
        self._identifiers[(tenant_id, identifier.channel, identifier.identifier)] = identifier
        if customer and identifier.channel not in customer.channels:
            customer.channels.append(identifier.channel)  # type: ignore[arg-type]
            customer.identifiers.append(identifier)

    def _tenant_of(self, customer_id: str) -> str:
        for (tid, cid), _ in self._customers.items():
            if cid == customer_id:
                return tid
        return ""

    async def list_identifiers(
        self, tenant_id: str, customer_id: str
    ) -> list[ChannelIdentifier]:
        return [
            i for (t, _, _), i in self._identifiers.items()
            if t == tenant_id and i.customer_id == customer_id
        ]

    async def record_candidate_link(self, link: CandidateLink) -> None:
        self._candidate_links[link.link_id] = link

    async def list_candidate_links(
        self, tenant_id: str, customer_id: str
    ) -> list[CandidateLink]:
        out = []
        for link in self._candidate_links.values():
            if customer_id in (link.customer_id_a, link.customer_id_b):
                out.append(link)
        return out

    # --- memories ---
    async def insert_memory(self, memory: Memory) -> None:
        self._memories[memory.memory_id] = memory

    async def supersede_memory(
        self, tenant_id: str, memory_id: str, superseded_by: str
    ) -> None:
        m = self._memories.get(memory_id)
        if not m or m.tenant_id != tenant_id:
            return  # cross-tenant attempts silently ignored
        self._memories[memory_id] = m.model_copy(update={
            "is_active": False,
            "superseded_by": superseded_by,
            "updated_at": utcnow(),
        })

    async def get_memories_by_ids(
        self, tenant_id: str, customer_id: str, ids: list[str]
    ) -> list[Memory]:
        out: list[Memory] = []
        for mid in ids:
            m = self._memories.get(mid)
            if m and m.tenant_id == tenant_id and m.customer_id == customer_id:
                out.append(m)
        return out

    async def list_memories(
        self,
        tenant_id: str,
        customer_id: str,
        *,
        limit: int = 50,
        active_only: bool = True,
        fact_type: str | None = None,
    ) -> list[Memory]:
        out: list[Memory] = []
        for m in self._memories.values():
            if m.tenant_id != tenant_id or m.customer_id != customer_id:
                continue
            if active_only and not m.is_active:
                continue
            if fact_type and m.fact_type != fact_type:
                continue
            out.append(m)
        out.sort(key=lambda m: (m.salience, m.created_at), reverse=True)
        return out[:limit]

    async def list_expired(self, now: datetime) -> list[Memory]:
        return [
            m for m in self._memories.values()
            if m.expires_at is not None and m.expires_at <= now and m.is_active
        ]

    async def delete_customer(self, tenant_id: str, customer_id: str) -> dict[str, int]:
        deleted = defaultdict(int)
        self._customers.pop((tenant_id, customer_id), None)
        deleted["customers"] += 1

        for key in list(self._identifiers.keys()):
            if key[0] == tenant_id and self._identifiers[key].customer_id == customer_id:
                del self._identifiers[key]
                deleted["identifiers"] += 1

        for mid in list(self._memories.keys()):
            m = self._memories[mid]
            if m.tenant_id == tenant_id and m.customer_id == customer_id:
                del self._memories[mid]
                deleted["memories"] += 1

        for lid in list(self._candidate_links.keys()):
            link = self._candidate_links[lid]
            if customer_id in (link.customer_id_a, link.customer_id_b):
                del self._candidate_links[lid]
                deleted["candidate_links"] += 1

        return dict(deleted)

    async def tenant_stats(self, tenant_id: str) -> dict[str, Any]:
        customers = [c for (t, _), c in self._customers.items() if t == tenant_id]
        memories = [m for m in self._memories.values() if m.tenant_id == tenant_id]
        channel_counts: dict[str, int] = defaultdict(int)
        for m in memories:
            channel_counts[m.source_channel] += 1
        return {
            "total_customers": len(customers),
            "total_memories": len(memories),
            "channels": dict(channel_counts),
            "avg_memories_per_customer": (
                len(memories) / len(customers) if customers else 0.0
            ),
        }

    async def close(self) -> None:
        self._customers.clear()
        self._identifiers.clear()
        self._memories.clear()
        self._candidate_links.clear()


class InMemorySemanticStore:
    def __init__(self) -> None:
        self._points: dict[str, tuple[str, str, list[float], dict[str, Any]]] = {}
        # memory_id -> (tenant_id, customer_id, embedding, metadata)

    async def upsert(
        self,
        tenant_id: str,
        customer_id: str,
        memory_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> str:
        self._points[memory_id] = (tenant_id, customer_id, embedding, {**metadata, "text": text})
        return memory_id

    async def search(
        self,
        tenant_id: str,
        customer_id: str,
        embedding: list[float],
        *,
        limit: int = 5,
    ) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        for mid, (tid, cid, vec, _meta) in self._points.items():
            if tid != tenant_id or cid != customer_id:
                continue
            scored.append((mid, _cosine(embedding, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def delete_customer(self, tenant_id: str, customer_id: str) -> int:
        count = 0
        for mid in list(self._points.keys()):
            tid, cid, _, _ = self._points[mid]
            if tid == tenant_id and cid == customer_id:
                del self._points[mid]
                count += 1
        return count

    async def close(self) -> None:
        self._points.clear()


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
