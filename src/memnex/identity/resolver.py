"""Identity resolution pipeline.

Resolution order (decreasing confidence):

1. **Hot cache**: ``(tenant, channel, identifier)`` already looked up recently.
2. **Deterministic**: same normalized identifier in the warm store.
3. **Manual link**: the caller explicitly linked two identifiers, which is
   handled by :meth:`link_identity`; subsequent resolves hit path (2).
4. **Fuzzy**: surfaces a *candidate* link but does not auto-merge.
5. **Create**: brand new customer.
"""
from __future__ import annotations

from memnex._time import utcnow

import uuid
from datetime import datetime

from memnex.config import MemnexConfig
from memnex.identity.fuzzy import FuzzyCandidate, find_candidates
from memnex.identity.models import (
    CandidateLink,
    Channel,
    ChannelIdentifier,
    Customer,
    Match,
)
from memnex.identity.normalizer import infer_type, normalize
from memnex.storage.base import HotStore, WarmStore

_DETERMINISTIC_TYPES = {"phone", "email", "whatsapp_id", "app_user_id"}


class IdentityResolver:
    def __init__(self, config: MemnexConfig, hot: HotStore, warm: WarmStore) -> None:
        self._cfg = config
        self._hot = hot
        self._warm = warm

    async def resolve(
        self,
        channel: Channel,
        identifier: str,
        *,
        hint_name: str | None = None,
        hint_topic: str | None = None,
        auto_create: bool = True,
    ) -> Customer:
        """Resolve a channel identifier to a customer, creating one if needed."""
        canonical = normalize(channel, identifier)
        ttl = self._cfg.redis_cache_ttl_hours * 3600

        # Path 1: cache.
        cached = await self._hot.get_identifier_cache(
            self._cfg.tenant_id, channel, canonical
        )
        if cached:
            c = await self._warm.get_customer(self._cfg.tenant_id, cached)
            if c:
                return c

        # Path 2: deterministic match in warm store.
        existing = await self._warm.find_by_identifier(
            self._cfg.tenant_id, channel, canonical
        )
        if existing:
            await self._hot.set_identifier_cache(
                self._cfg.tenant_id, channel, canonical, existing.id, ttl
            )
            return existing

        # Path 3 skipped (manual links land in path 2 once written).

        # Path 4: fuzzy (never auto-merges — only records a candidate).
        if hint_name or hint_topic:
            await self._maybe_record_fuzzy(channel, canonical, hint_name, hint_topic)

        # Path 5: create a new customer.
        if not auto_create:
            raise KeyError(f"No customer for {channel}:{identifier}")

        return await self._create_customer(channel, canonical, hint_name, hint_topic, ttl)

    async def link_identity(
        self,
        customer_id: str,
        channel: Channel,
        identifier: str,
        linked_by: str = "manual",
    ) -> ChannelIdentifier:
        canonical = normalize(channel, identifier)
        ident = ChannelIdentifier(
            identifier_id=str(uuid.uuid4()),
            customer_id=customer_id,
            channel=channel,
            identifier=canonical,
            identifier_type=infer_type(channel, identifier),
            confidence=1.0 if linked_by != "fuzzy_confirmed" else 0.95,
            linked_by=linked_by,  # type: ignore[arg-type]
            created_at=utcnow(),
        )
        await self._warm.add_identifier(ident)
        ttl = self._cfg.redis_cache_ttl_hours * 3600
        await self._hot.set_identifier_cache(
            self._cfg.tenant_id, channel, canonical, customer_id, ttl
        )
        return ident

    async def check_match(
        self,
        identifier_a: tuple[Channel, str],
        identifier_b: tuple[Channel, str],
    ) -> Match:
        ca = normalize(*identifier_a)
        cb = normalize(*identifier_b)

        # Same normalized identifier & same channel: trivially the same.
        if identifier_a[0] == identifier_b[0] and ca == cb:
            existing = await self._warm.find_by_identifier(
                self._cfg.tenant_id, identifier_a[0], ca
            )
            return Match(
                is_same=True,
                confidence=1.0,
                customer_id=existing.id if existing else None,
                linked_by="system",
                evidence={"normalized_equal": True},
            )

        # Otherwise: same person only if both resolve to the same customer.
        ca_customer = await self._warm.find_by_identifier(
            self._cfg.tenant_id, identifier_a[0], ca
        )
        cb_customer = await self._warm.find_by_identifier(
            self._cfg.tenant_id, identifier_b[0], cb
        )
        if ca_customer and cb_customer and ca_customer.id == cb_customer.id:
            ident = next(
                (i for i in ca_customer.identifiers if i.channel == identifier_b[0]),
                None,
            )
            return Match(
                is_same=True,
                confidence=1.0,
                customer_id=ca_customer.id,
                linked_by=ident.linked_by if ident else "system",
                evidence={"shared_customer_id": True},
            )
        return Match(is_same=False, confidence=0.0)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _create_customer(
        self,
        channel: Channel,
        canonical: str,
        name: str | None,
        topic: str | None,
        ttl: int,
    ) -> Customer:
        now = utcnow()
        customer_id = str(uuid.uuid4())
        metadata: dict = {}
        if name:
            metadata["name"] = name
        if topic:
            metadata["last_topic"] = topic

        customer = Customer(
            id=customer_id,
            tenant_id=self._cfg.tenant_id,
            created_at=now,
            last_seen_at=now,
            last_channel=channel,
            channels=[channel],
            metadata=metadata,
        )
        await self._warm.upsert_customer(customer)

        ident = ChannelIdentifier(
            identifier_id=str(uuid.uuid4()),
            customer_id=customer_id,
            channel=channel,
            identifier=canonical,
            identifier_type=infer_type(channel, canonical),
            confidence=1.0,
            linked_by="system",
            created_at=now,
        )
        await self._warm.add_identifier(ident)
        customer.identifiers.append(ident)

        await self._hot.set_identifier_cache(
            self._cfg.tenant_id, channel, canonical, customer_id, ttl
        )
        return customer

    async def _maybe_record_fuzzy(
        self,
        channel: Channel,
        canonical: str,
        name: str | None,
        topic: str | None,
    ) -> list[FuzzyCandidate]:
        # Only meaningful if the warm store can enumerate candidates. The
        # in-memory backend always can; a Postgres backend would need a
        # recent-activity query. For Postgres we skip to avoid N+1 scans.
        candidates = await self._enumerate_recent(channel)
        if not candidates:
            return []
        found = find_candidates(
            candidates,
            new_name=name,
            new_topic=topic,
            now=utcnow(),
            window_hours=self._cfg.fuzzy_match_window_hours,
        )
        for fc in found:
            link = CandidateLink(
                link_id=str(uuid.uuid4()),
                customer_id_a=fc.customer_id,
                customer_id_b="",  # no customer yet for the incoming identity
                confidence=fc.confidence,
                evidence={**fc.evidence, "incoming": {"channel": channel, "id": canonical}},
                status="pending",
                created_at=utcnow(),
            )
            await self._warm.record_candidate_link(link)
        return found

    async def _enumerate_recent(self, _channel: Channel) -> list[Customer]:
        # Backend-specific enumeration is out of scope; the in-memory store
        # exposes all customers via the private dict, but we don't reach in.
        # Subclasses/backends can override this behavior later.
        return []
