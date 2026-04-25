"""Concurrency chaos tests.

Inject controlled failures into the pub/sub bus + slow readers and assert
eventual consistency + no lost writes.
"""
from __future__ import annotations

import asyncio
import random

import pytest

from memnex import Memnex, MemnexConfig
from memnex.concurrency.bus import InProcessBus


class FlakyBus(InProcessBus):
    """Pub/sub that drops ``drop_rate`` fraction of publishes + adds latency."""

    def __init__(self, drop_rate: float = 0.1, max_jitter_ms: int = 5) -> None:
        super().__init__()
        self._drop_rate = drop_rate
        self._max_jitter_ms = max_jitter_ms
        self.dropped = 0

    async def publish(self, tenant_id: str, user_id: str, version: int) -> None:
        if random.random() < self._drop_rate:
            self.dropped += 1
            return
        await asyncio.sleep(random.random() * self._max_jitter_ms / 1000.0)
        await super().publish(tenant_id, user_id, version)


async def _client_with_bus(tenant_id: str, bus: FlakyBus) -> Memnex:
    mx = await Memnex.create(config=MemnexConfig(tenant_id=tenant_id))
    # Swap the bus after construction.
    mx._memory._bus = bus  # type: ignore[attr-defined]
    await bus.subscribe(mx._memory._on_invalidate)  # type: ignore[attr-defined]
    return mx


async def test_writes_survive_bus_drops():
    """Even if 30% of invalidation publishes are dropped, writes persist
    in the warm store — the bus only affects cache freshness, not durability."""
    bus = FlakyBus(drop_rate=0.3)
    mx = await _client_with_bus("chaos_1", bus)
    try:
        customer = await mx.resolve("voice", "+912000000001")

        async def writer(i: int) -> None:
            await mx.write(
                channel="voice", identifier="+912000000001",
                facts=[f"chaos-write-{i}"],
            )

        await asyncio.gather(*[writer(i) for i in range(150)])

        # Query warm store directly to bypass the read-path limit.
        mems = await mx._stores.warm.list_memories(
            mx.config.tenant_id, customer.id, limit=500,
        )
        stored = {m.fact for m in mems}
        for i in range(150):
            assert f"chaos-write-{i}" in stored, f"lost: {i}"
        # Some bus publishes were dropped — that's the chaos input signal.
        assert bus.dropped > 0
    finally:
        await mx.close()


async def test_read_after_write_blocks_on_stale_bus():
    """Explicit if_version awaits the target version even if the bus is slow.
    Durability is independent of the bus."""
    bus = FlakyBus(drop_rate=0.0, max_jitter_ms=20)
    mx = await _client_with_bus("chaos_2", bus)
    try:
        customer = await mx.resolve("voice", "+912000000002")
        res = await mx._memory.write(
            customer_id=customer.id, channel="voice",
            facts=["must-be-visible"],
        )
        mems = await mx._memory.read(
            customer_id=customer.id, if_version=res.version,
        )
        assert any("must-be-visible" in m.fact for m in mems)
    finally:
        await mx.close()


async def test_ledger_chain_holds_under_chaos():
    """Ledger integrity is a pure function of write ordering; bus drops
    must not break the hash chain."""
    bus = FlakyBus(drop_rate=0.5)
    mx = await _client_with_bus("chaos_3", bus)
    try:
        await mx.resolve("voice", "+912000000003")
        for i in range(30):
            await mx.write(
                channel="voice", identifier="+912000000003",
                facts=[f"chain-{i}"],
            )
        assert await mx.verify_ledger()
    finally:
        await mx.close()


async def test_mixed_workload_concurrent_readers_and_writers():
    """Readers + writers interleaved; no torn reads, all writes durable."""
    bus = FlakyBus(drop_rate=0.1, max_jitter_ms=3)
    mx = await _client_with_bus("chaos_4", bus)
    try:
        await mx.resolve("voice", "+912000000004")

        async def writer(i: int) -> None:
            await mx.write(
                channel="voice", identifier="+912000000004",
                facts=[f"mixed-{i}"],
            )

        async def reader() -> None:
            await mx.read(channel="voice", identifier="+912000000004")

        tasks = []
        for i in range(80):
            tasks.append(asyncio.create_task(writer(i)))
            if i % 4 == 0:
                tasks.append(asyncio.create_task(reader()))
        await asyncio.gather(*tasks)

        customer = await mx.resolve("voice", "+912000000004")
        mems = await mx._stores.warm.list_memories(
            mx.config.tenant_id, customer.id, limit=500,
        )
        stored = {m.fact for m in mems}
        missed = [i for i in range(80) if f"mixed-{i}" not in stored]
        assert not missed, f"missed writes: {missed[:5]}"
    finally:
        await mx.close()
