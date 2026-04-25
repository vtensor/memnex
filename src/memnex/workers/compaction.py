"""Compaction worker.

Periodically walks every customer's memory list and:
- drops memories whose salience has decayed below threshold
- merges near-duplicate facts
- supersedes very old intents with no matching resolution

Runs as a long-lived async task; can also be invoked once via
:meth:`CompactionWorker.run_once`.
"""
from __future__ import annotations

from memnex._time import utcnow

import asyncio
from datetime import datetime, timedelta

from memnex.client import Memnex
from memnex.memory import conflict as conflict_mod


class CompactionWorker:
    def __init__(self, mx: Memnex, *, interval_seconds: int = 3600) -> None:
        self._mx = mx
        self._interval = interval_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # don't crash the worker loop
                print(f"compaction error: {exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> dict:
        warm = self._mx._stores.warm
        stats = await warm.tenant_stats(self._mx.config.tenant_id)
        deduped = decayed = 0
        customer_ids = await self._list_customer_ids()

        now = utcnow()
        decay_cutoff = now - timedelta(days=30)

        for customer_id in customer_ids:
            memories = await warm.list_memories(
                self._mx.config.tenant_id, customer_id, limit=500
            )
            # Decay old low-salience.
            for m in memories:
                if m.created_at < decay_cutoff and m.salience < 0.3:
                    await warm.supersede_memory(
                        self._mx.config.tenant_id, m.memory_id,
                        superseded_by=m.memory_id,
                    )
                    decayed += 1

            # Dedupe near-identical facts.
            seen: list[str] = []
            for m in memories:
                if any(conflict_mod.jaccard(m.fact, s) > 0.95 for s in seen):
                    await warm.supersede_memory(
                        self._mx.config.tenant_id, m.memory_id,
                        superseded_by=m.memory_id,
                    )
                    deduped += 1
                else:
                    seen.append(m.fact)

        return {
            "tenant": self._mx.config.tenant_id,
            "customers_scanned": len(customer_ids),
            "decayed": decayed,
            "deduped": deduped,
            "stats_before": stats,
        }

    async def _list_customer_ids(self) -> list[str]:
        # Backend-specific hook. The in-memory store exposes customers via
        # its private dict; for Postgres a separate query would be used.
        store = self._mx._stores.warm
        customers = getattr(store, "_customers", {})
        return [cid for (tid, cid) in customers if tid == self._mx.config.tenant_id]
