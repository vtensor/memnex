"""Top-level Memnex client.

Two public API surfaces:

1. The legacy **identity-first** API (``write`` / ``read`` / ``search`` +
   ``resolve`` / ``link_identity``) used by examples and the Python-SDK
   path. It routes every op through ``IdentityResolver``.

2. The **user-scoped** API (``user_write`` / ``user_read`` /
   ``user_search`` / ``user_forget`` / ``user_trace``) used by the MCP
   SaaS path. The tenant passes an opaque ``user_id`` and we derive a
   deterministic ``customer_id = uuid5(NAMESPACE, tenant_id + user_id)``.
   No identity resolution — the tenant owns the user mapping.

The second path is what the MCP server calls. It keeps the SaaS surface
free of the phone / email normalization assumptions baked into identity
resolution.
"""
from __future__ import annotations

import uuid
from typing import Any

from memnex._time import utcnow
from memnex.channels.base import get_adapter
from memnex.config import MemnexConfig
from memnex.identity.models import Channel, Customer, Match
from memnex.identity.resolver import IdentityResolver
from memnex.memory.manager import MemoryManager
from memnex.memory.models import Fact, Memory
from memnex.privacy.gdpr import GDPRCoordinator
from memnex.storage.factory import Stores, open_stores

# Fixed namespace for deterministic customer_id derivation from
# (tenant_id, user_id). Stable across processes so the same inputs always
# map to the same customer row.
_USER_NS = uuid.UUID("d8d6b3c2-1b7c-4f78-9c66-5e7c8f4b0a01")


class Memnex:
    def __init__(
        self,
        config: MemnexConfig,
        stores: Stores,
    ) -> None:
        self._cfg = config
        self._stores = stores
        self._identity = IdentityResolver(config, stores.hot, stores.warm)
        self._memory = MemoryManager(
            config,
            stores.hot, stores.warm, stores.semantic,
            versions=stores.versions,
            bus=stores.bus,
        )
        self._gdpr = GDPRCoordinator(config, stores.hot, stores.warm, stores.semantic)

    @classmethod
    async def create(
        cls,
        tenant_id: str | None = None,
        *,
        config: MemnexConfig | None = None,
        **overrides: Any,
    ) -> "Memnex":
        if config is None:
            if tenant_id is None:
                raise ValueError("Pass tenant_id or config=")
            config = MemnexConfig(tenant_id=tenant_id, **overrides)
        stores = await open_stores(config)
        return cls(config, stores)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def config(self) -> MemnexConfig:
        return self._cfg

    async def resolve(
        self,
        channel: Channel,
        identifier: str,
        *,
        hint_name: str | None = None,
        hint_topic: str | None = None,
        auto_create: bool = True,
    ) -> Customer:
        return await self._identity.resolve(
            channel,
            identifier,
            hint_name=hint_name,
            hint_topic=hint_topic,
            auto_create=auto_create,
        )

    async def link_identity(
        self,
        *,
        customer_id: str,
        channel: Channel,
        identifier: str,
        linked_by: str = "manual",
    ):
        return await self._identity.link_identity(
            customer_id, channel, identifier, linked_by=linked_by
        )

    async def check_match(
        self,
        identifier_a: tuple[Channel, str],
        identifier_b: tuple[Channel, str],
    ) -> Match:
        return await self._identity.check_match(identifier_a, identifier_b)

    async def write(
        self,
        *,
        channel: Channel,
        identifier: str,
        facts: list[str] | list[Fact] | None = None,
        raw_text: str | None = None,
        session_id: str | None = None,
        source_agent_id: str | None = None,
        ttl_hours: int | None = None,
        metadata: dict | None = None,
        trust_level: str | int = "user_content",
        source: str | None = None,
    ) -> list[Memory]:
        customer = await self._identity.resolve(channel, identifier)

        # Let the adapter pre-clean raw text (voice filler, WhatsApp media, etc).
        if raw_text is not None:
            raw_text = get_adapter(channel).extract(raw_text, metadata)

        return await self._memory.write(
            customer_id=customer.id,
            channel=channel,
            facts=facts,
            raw_text=raw_text,
            session_id=session_id,
            source_agent_id=source_agent_id,
            ttl_hours=ttl_hours,
            metadata=metadata,
            trust_level=trust_level,
            source=source,
        )

    async def read(
        self,
        *,
        channel: Channel,
        identifier: str,
        target_channel: Channel | None = None,
        token_budget: int | None = None,
        fact_type: str | None = None,
        as_text: bool = True,
        if_version: int | None = None,
    ) -> str | list[Memory]:
        customer = await self._identity.resolve(channel, identifier, auto_create=False)
        memories = await self._memory.read(
            customer_id=customer.id,
            token_budget=token_budget,
            fact_type=fact_type,
            if_version=if_version,
        )
        if not as_text:
            return memories
        adapter = get_adapter(target_channel or channel)
        return adapter.format(memories)

    async def current_version(self, *, customer_id: str) -> int:
        """Current monotonic version for this user. Bumps on every write."""
        return await self._memory._versions.current(self._cfg.tenant_id, customer_id)

    async def verify_ledger(self) -> bool:
        """Verify the hash chain of the write ledger."""
        return await self._memory._ledger.verify_chain(tenant_id=self._cfg.tenant_id)

    async def read_wrapped(
        self,
        *,
        channel: Channel,
        identifier: str,
        token_budget: int | None = None,
    ) -> tuple[str, str]:
        """Read and wrap untrusted memories in <untrusted_memory> tags.

        Returns (wrapped_text, nonce). Pass the matching system prompt addition
        (memnex.provenance.wrapping.AGENT_SYSTEM_PROMPT_ADDITION) to the agent.
        """
        from memnex.provenance.wrapping import wrap_for_agent
        memories = await self.read(
            channel=channel,
            identifier=identifier,
            token_budget=token_budget,
            as_text=False,
        )
        return wrap_for_agent(memories, self._memory._policy)  # type: ignore[arg-type]

    def drain_alerts(self) -> list[dict]:
        """Return + clear security alerts (injection attempts, policy violations)."""
        return self._memory.drain_alerts()

    async def trace_output(
        self,
        *,
        channel: Channel,
        identifier: str,
        agent_output: str,
    ) -> list[dict]:
        """Which stored memories could have produced this agent output?

        Empty list = suspected hallucination. Returned items have
        ``memory_id``, ``fact``, ``match_type``, ``score``.
        """
        from memnex.audit.trace import trace_output as _trace
        memories = await self.read(
            channel=channel, identifier=identifier, as_text=False,
        )
        hits = _trace(agent_output, memories)  # type: ignore[arg-type]
        return [
            {"memory_id": h.memory_id, "fact": h.fact,
             "match_type": h.match_type, "score": h.score}
            for h in hits
        ]

    async def search(
        self,
        *,
        channel: Channel,
        identifier: str,
        query: str,
        max_results: int = 5,
    ) -> list[Memory]:
        customer = await self._identity.resolve(channel, identifier, auto_create=False)
        return await self._memory.search(
            customer_id=customer.id,
            query=query,
            max_results=max_results,
        )

    # --- privacy ---
    async def forget_customer(self, *, customer_id: str, reason: str) -> dict:
        return await self._gdpr.forget_customer(customer_id, reason)

    async def export_customer_data(
        self, *, customer_id: str, format: str = "json"
    ) -> dict | str:
        return await self._gdpr.export_customer_data(customer_id, format=format)

    # --- admin ---
    async def get_timeline(
        self, *, customer_id: str, limit: int = 50
    ) -> list[Memory]:
        memories = await self._stores.warm.list_memories(
            self._cfg.tenant_id, customer_id, limit=limit, active_only=False
        )
        return sorted(memories, key=lambda m: m.created_at)

    async def stats(self) -> dict:
        return await self._stores.warm.tenant_stats(self._cfg.tenant_id)

    async def close(self) -> None:
        await self._stores.close()

    # ------------------------------------------------------------------
    # User-scoped API — MCP / SaaS path
    # ------------------------------------------------------------------
    def _customer_id_for(self, user_id: str) -> str:
        """Derive a deterministic UUID from ``(tenant_id, user_id)``.

        Same inputs always produce the same output — lets every Memnex
        process in the fleet agree on which ``customer_id`` row belongs
        to which tenant's ``user_id``.
        """
        return str(uuid.uuid5(_USER_NS, f"{self._cfg.tenant_id}:{user_id}"))

    async def _ensure_customer(self, user_id: str, channel: str) -> str:
        """Return ``customer_id``, creating the row if missing."""
        customer_id = self._customer_id_for(user_id)
        existing = await self._stores.warm.get_customer(
            self._cfg.tenant_id, customer_id,
        )
        if existing is None:
            now = utcnow()
            await self._stores.warm.upsert_customer(Customer(
                id=customer_id,
                tenant_id=self._cfg.tenant_id,
                created_at=now,
                last_seen_at=now,
                last_channel=channel,  # type: ignore[arg-type]
                metadata={"user_id": user_id},
            ))
        return customer_id

    async def user_write(
        self,
        *,
        user_id: str,
        channel: str,
        facts: list[str] | list[Fact] | None = None,
        raw_text: str | None = None,
        session_id: str | None = None,
        source_agent_id: str | None = None,
        ttl_hours: int | None = None,
        trust_level: str | int = "user_content",
        source: str | None = None,
        metadata: dict | None = None,
    ) -> list[Memory]:
        customer_id = await self._ensure_customer(user_id, channel)
        if raw_text is not None:
            raw_text = get_adapter(channel).extract(raw_text, metadata)  # type: ignore[arg-type]
        return await self._memory.write(
            customer_id=customer_id,
            channel=channel,
            facts=facts,
            raw_text=raw_text,
            session_id=session_id,
            source_agent_id=source_agent_id,
            ttl_hours=ttl_hours,
            trust_level=trust_level,
            source=source,
            metadata=metadata,
        )

    async def user_read(
        self,
        *,
        user_id: str,
        channel: str,
        target_format: str | None = None,
        token_budget: int | None = None,
        fact_type: str | None = None,
        as_text: bool = True,
        if_version: int | None = None,
    ) -> str | list[Memory]:
        customer_id = self._customer_id_for(user_id)
        memories = await self._memory.read(
            customer_id=customer_id,
            token_budget=token_budget,
            fact_type=fact_type,
            if_version=if_version,
        )
        if not as_text:
            return memories
        adapter = get_adapter(target_format or channel)
        return adapter.format(memories)

    async def user_search(
        self,
        *,
        user_id: str,
        query: str,
        max_results: int = 5,
    ) -> list[Memory]:
        customer_id = self._customer_id_for(user_id)
        return await self._memory.search(
            customer_id=customer_id,
            query=query,
            max_results=max_results,
        )

    async def user_forget(
        self,
        *,
        user_id: str,
        reason: str = "gdpr_request",
    ) -> dict:
        customer_id = self._customer_id_for(user_id)
        return await self._gdpr.forget_customer(customer_id, reason)

    async def user_trace(
        self,
        *,
        user_id: str,
        agent_output: str,
    ) -> list[dict]:
        from memnex.audit.trace import trace_output as _trace
        customer_id = self._customer_id_for(user_id)
        memories = await self._memory.read(customer_id=customer_id)
        hits = _trace(agent_output, memories)
        return [
            {"memory_id": h.memory_id, "fact": h.fact,
             "match_type": h.match_type, "score": h.score}
            for h in hits
        ]

    async def __aenter__(self) -> "Memnex":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
