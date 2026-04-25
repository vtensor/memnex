"""Memory manager — orchestrates write, read, and search paths."""
from __future__ import annotations

import uuid
from datetime import timedelta

from memnex._time import utcnow
from memnex.concurrency.bus import InvalidationBus, InProcessBus
from memnex.concurrency.ledger import InMemoryLedger, WriteLedger
from memnex.concurrency.versions import InProcessVersionClock, VersionClock
from memnex.config import MemnexConfig
from memnex.memory import conflict as conflict_mod
from memnex.memory import salience as salience_mod
from memnex.memory.compressor import compress
from memnex.memory.embeddings import Embedder, build_embedder
from memnex.memory.extractor import Extractor, build_extractor
from memnex.memory.models import Fact, Memory
from memnex.privacy.masker import PIIMasker
from memnex.provenance.filter import InjectionFilter
from memnex.provenance.policy import PolicyViolation, TrustLevel, TrustPolicy
from memnex.storage.base import HotStore, SemanticStore, WarmStore


class WriteResult:
    """Result of a write: memories + the version at commit time + ledger ref + receipt."""

    def __init__(
        self,
        memories: list[Memory],
        version: int,
        ledger_seq: int,
        receipt: dict | None = None,
    ) -> None:
        self.memories = memories
        self.version = version
        self.ledger_seq = ledger_seq
        self.receipt = receipt

    def __iter__(self):
        # backward-compatibility: callers that do `for m in write(...)` still work
        return iter(self.memories)

    def __len__(self) -> int:
        return len(self.memories)

    def __getitem__(self, i):
        return self.memories[i]


class MemoryManager:
    def __init__(
        self,
        config: MemnexConfig,
        hot: HotStore,
        warm: WarmStore,
        semantic: SemanticStore,
        *,
        extractor: Extractor | None = None,
        embedder: Embedder | None = None,
        masker: PIIMasker | None = None,
        versions: VersionClock | None = None,
        bus: InvalidationBus | None = None,
        ledger: WriteLedger | None = None,
    ) -> None:
        self._cfg = config
        self._hot = hot
        self._warm = warm
        self._semantic = semantic
        self._extractor = extractor or build_extractor(config)
        self._embedder = embedder or build_embedder(config)
        self._masker = masker or PIIMasker(config)
        self._versions: VersionClock = versions or InProcessVersionClock()
        self._bus: InvalidationBus = bus or InProcessBus()
        self._ledger: WriteLedger = ledger or InMemoryLedger()
        self._policy: TrustPolicy = (
            TrustPolicy(**(config.trust_policy or {}))
            if config.trust_policy is not None
            else TrustPolicy()
        )
        self._filter = InjectionFilter()
        self._alerts: list[dict] = []
        # Self-subscribe to invalidate local cache on any publish
        import asyncio
        self._bus_ready = asyncio.ensure_future(self._bus.subscribe(self._on_invalidate))

    async def _on_invalidate(self, tenant_id: str, user_id: str, version: int) -> None:
        await self._hot.invalidate(tenant_id, user_id)

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------
    async def write(
        self,
        *,
        customer_id: str,
        channel: str,
        facts: list[str] | list[Fact] | None = None,
        raw_text: str | None = None,
        session_id: str | None = None,
        source_agent_id: str | None = None,
        ttl_hours: int | None = None,
        metadata: dict | None = None,
        trust_level: TrustLevel | str | int = TrustLevel.user_content,
        source: str | None = None,
    ) -> list[Memory]:
        if facts is None and raw_text is None:
            raise ValueError("Pass either facts=... or raw_text=...")

        trust = TrustLevel.parse(trust_level)

        # 0) Injection filter: tainted content never reaches the extractor.
        if self._policy.reject_injection_patterns:
            for content in (
                [raw_text] if raw_text else
                [str(f) if not isinstance(f, Fact) else f.fact for f in (facts or [])]
            ):
                if content and not self._filter.is_safe(content):
                    hits = self._filter.scan(content)
                    self._alerts.append({
                        "tenant_id": self._cfg.tenant_id,
                        "customer_id": customer_id,
                        "reason": "injection_pattern",
                        "pattern": hits[0].pattern if hits else None,
                        "ts": utcnow().isoformat(),
                    })
                    raise PolicyViolation(
                        f"injection pattern detected: {hits[0].pattern if hits else 'unknown'}"
                    )

        # 1) Extract or accept facts. Three input shapes supported:
        #    - Fact objects      -> used as-is (recommended, fastest path)
        #    - dict {fact, type, entities, confidence} -> coerced to Fact
        #    - plain strings     -> classified by the rule-based extractor
        #    - raw_text          -> run through the LLM/rule extractor
        # The structured-input paths bypass the LLM entirely.
        if raw_text is not None:
            extracted = await self._extractor.extract(raw_text, channel=channel)
        else:
            from memnex.memory.extractor import RuleBasedExtractor
            classifier = RuleBasedExtractor()
            extracted = []
            for f in (facts or []):
                if isinstance(f, Fact):
                    extracted.append(f)
                    continue
                if isinstance(f, dict):
                    # Coerce a structured dict directly into a Fact. Validation
                    # errors (missing/typo fields, bad type enum, out-of-range
                    # confidence) raise immediately — fail fast, don't silently
                    # stringify.
                    extracted.append(Fact(**f))
                    continue
                classified = await classifier.extract(str(f), channel=channel)
                if classified:
                    extracted.extend(classified)
                else:
                    extracted.append(Fact(fact=str(f)))

        # 2) PII masking at write time (never read time).
        extracted = [self._masker.mask_fact(f) for f in extracted]

        # 3) Score & drop low-salience.
        scored: list[tuple[Fact, float]] = []
        for f in extracted:
            s = salience_mod.score(f)
            if s < self._cfg.salience_drop_threshold:
                continue
            scored.append((f, s))

        # Respect the per-write cap.
        scored = scored[: self._cfg.max_facts_per_write]

        if not scored:
            return []

        # 4) Conflict check against existing memories. Precompute everything
        # we need — including the final memory_ids — so we can write the
        # ledger entry BEFORE any storage mutation. The ledger is the
        # source of truth; if it fails, the whole write aborts.
        existing = await self._warm.list_memories(
            self._cfg.tenant_id, customer_id, limit=100
        )

        now = utcnow()
        expires_at = (
            now + timedelta(hours=ttl_hours) if ttl_hours is not None else None
        )

        # Build memory objects + conflict plan without touching storage.
        planned: list[tuple[Memory, float, list]] = []
        for fact, sal in scored:
            # Trust policy check per fact type.
            try:
                self._policy.check(fact.type, trust)
            except PolicyViolation as exc:
                self._alerts.append({
                    "tenant_id": self._cfg.tenant_id,
                    "customer_id": customer_id,
                    "reason": "policy_violation",
                    "detail": str(exc),
                    "ts": utcnow().isoformat(),
                })
                # Drop this fact but don't fail the whole write — one bad
                # fact in a batch shouldn't nuke the others.
                continue

            conflicts = conflict_mod.detect(
                fact,
                existing,
                similarity_threshold=self._cfg.conflict_similarity_threshold,
            )

            merged_meta = {
                **(metadata or {}),
                "trust_level": trust.name,
                "source": source or channel,
            }
            memory = Memory(
                memory_id=str(uuid.uuid4()),
                tenant_id=self._cfg.tenant_id,
                customer_id=customer_id,
                fact=fact.fact,
                fact_type=fact.type,
                entities=fact.entities,
                salience=sal,
                source_channel=channel,
                source_agent_id=source_agent_id,
                session_id=session_id,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                contains_pii=bool(getattr(fact, "pii_fields", None)),
                pii_fields=getattr(fact, "pii_fields", []) or [],
                metadata=merged_meta,
            )
            planned.append((memory, sal, conflicts))

        if not planned:
            return WriteResult([], version=await self._versions.current(
                self._cfg.tenant_id, customer_id,
            ), ledger_seq=0, receipt=None)

        # 5) DURABILITY FIRST: bump version + append to ledger BEFORE any
        # storage mutation. If the ledger cannot persist, the whole write
        # is aborted and no observable state has changed.
        version = await self._versions.bump(self._cfg.tenant_id, customer_id)
        planned_ids = [m.memory_id for m, _, _ in planned]
        ledger_entry = await self._ledger.append(
            tenant_id=self._cfg.tenant_id,
            user_id=customer_id,
            version=version,
            op="write",
            payload={
                "memory_ids": planned_ids,
                "session_id": session_id,
                "channel": channel,
                "trust_level": trust.name,
            },
        )

        # 6) Now mutate storage. Ledger already promises these writes.
        written: list[Memory] = []
        for memory, sal, conflicts in planned:
            for c in conflicts:
                conflict_mod.apply_strategy(c, self._cfg.conflict_strategy)
                if c.resolution == "supersede":
                    await self._warm.supersede_memory(
                        self._cfg.tenant_id,
                        c.existing.memory_id,
                        superseded_by=memory.memory_id,
                    )

            embedding = await self._embedder.embed(memory.fact)
            embedding_id = await self._semantic.upsert(
                self._cfg.tenant_id,
                customer_id,
                memory.memory_id,
                memory.fact,
                embedding,
                {"fact_type": memory.fact_type, "channel": channel, "salience": sal},
            )
            memory = memory.model_copy(update={"embedding_id": embedding_id})

            await self._warm.insert_memory(memory)
            written.append(memory)

        # 7) Sign receipt, invalidate caches, publish bus notification.
        from memnex.audit.receipts import sign_receipt
        receipt = sign_receipt(
            op="write",
            tenant_id=self._cfg.tenant_id,
            customer_id=customer_id,
            payload={
                "memory_ids": [m.memory_id for m in written],
                "version": version,
                "ledger_seq": ledger_entry.seq,
                "ledger_hash": ledger_entry.payload_hash,
            },
        )
        await self._hot.invalidate(self._cfg.tenant_id, customer_id)
        try:
            await self._bus.publish(self._cfg.tenant_id, customer_id, version)
        except Exception:
            # Bus is best-effort. Durability (ledger + warm store) has
            # already been achieved; bus failure must not fail the write.
            pass
        return WriteResult(
            written, version=version, ledger_seq=ledger_entry.seq,
            receipt=receipt.to_dict(),
        )

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------
    async def read(
        self,
        *,
        customer_id: str,
        token_budget: int | None = None,
        fact_type: str | None = None,
        if_version: int | None = None,
    ) -> list[Memory]:
        """Read memories.

        ``if_version``: block until the user's version is at least this value,
        giving strict read-after-write. Useful in fan-out scenarios where the
        caller just wrote (version=N) and another instance needs to observe it.
        """
        budget = token_budget or self._cfg.default_token_budget
        ttl = self._cfg.redis_cache_ttl_hours * 3600

        if if_version is not None:
            await self._await_version(customer_id, if_version)

        cached = await self._hot.get_working_memory(self._cfg.tenant_id, customer_id)
        if cached is not None:
            return compress(cached, token_budget=budget)

        memories = await self._warm.list_memories(
            self._cfg.tenant_id, customer_id, limit=100, fact_type=fact_type
        )
        await self._hot.set_working_memory(
            self._cfg.tenant_id, customer_id, memories, ttl
        )
        return compress(memories, token_budget=budget)

    def drain_alerts(self) -> list[dict]:
        """Return and clear provenance / policy violation alerts.

        Tenants forward these to their SIEM.
        """
        out = list(self._alerts)
        self._alerts.clear()
        return out

    async def _await_version(self, customer_id: str, target: int, timeout_s: float = 2.0) -> None:
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            current = await self._versions.current(self._cfg.tenant_id, customer_id)
            if current >= target:
                return
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(
                    f"timed out waiting for version {target} (saw {current})"
                )
            await asyncio.sleep(0.005)

    async def search(
        self,
        *,
        customer_id: str,
        query: str,
        max_results: int = 5,
    ) -> list[Memory]:
        embedding = await self._embedder.embed(query)
        hits = await self._semantic.search(
            self._cfg.tenant_id, customer_id, embedding, limit=max_results
        )
        if not hits:
            return []
        # Hydrate only the hit ids — O(k) rather than scan-and-join.
        ids = [mid for mid, _score in hits]
        mems = await self._warm.get_memories_by_ids(
            self._cfg.tenant_id, customer_id, ids,
        )
        by_id = {m.memory_id: m for m in mems}
        # Preserve semantic-hit ordering.
        return [by_id[mid] for mid, _ in hits if mid in by_id]
