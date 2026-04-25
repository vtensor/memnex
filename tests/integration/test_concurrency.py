"""Concurrency tests + benchmarks.

These tests assert the A-pillar invariants:
- no lost writes under concurrent writers,
- monotonic per-user version,
- read-after-write consistency via ``if_version``,
- cache invalidation across writer/reader pairs,
- ledger hash chain integrity.

Output numbers are consumed by tests/reports/concurrency.md. The test
module also exposes a ``bench_*`` function used by the reporter script.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from memnex import Memnex, MemnexConfig


async def _client(tid: str) -> Memnex:
    return await Memnex.create(config=MemnexConfig(tenant_id=tid))


async def test_no_lost_writes_under_concurrency(mx_isolated):
    """N concurrent writers on the SAME user must all persist."""
    mx = mx_isolated
    await mx.resolve("voice", "+911001001001")

    N = 100

    async def writer(i: int) -> None:
        await mx.write(
            channel="voice", identifier="+911001001001",
            facts=[f"write #{i}"],
        )

    await asyncio.gather(*[writer(i) for i in range(N)])

    memories = await mx.read(
        channel="voice", identifier="+911001001001", as_text=False,
    )
    stored_texts = {m.fact for m in memories}
    for i in range(N):
        assert f"write #{i}" in stored_texts, f"lost write #{i}"


async def test_version_is_monotonic(mx_isolated):
    """Version bumps are monotonic per user even under parallel writes."""
    mx = mx_isolated
    customer = await mx.resolve("voice", "+911001001002")

    N = 50

    async def write(i: int) -> int:
        res = await mx._memory.write(
            customer_id=customer.id, channel="voice",
            facts=[f"fact #{i}"],
        )
        return res.version

    versions = await asyncio.gather(*[write(i) for i in range(N)])
    # Every bump is unique — no two writers got the same version.
    assert len(set(versions)) == N
    assert max(versions) == N


async def test_read_after_write_with_if_version(mx_isolated):
    """if_version blocks until the read path sees the target version."""
    mx = mx_isolated
    customer = await mx.resolve("voice", "+911001001003")

    async def writer_then_verify():
        res = await mx._memory.write(
            customer_id=customer.id, channel="voice",
            facts=["critical state change"],
        )
        # Explicit read-after-write with if_version.
        memories = await mx._memory.read(
            customer_id=customer.id,
            if_version=res.version,
        )
        assert any("critical state change" in m.fact for m in memories)

    await writer_then_verify()


async def test_cache_invalidation_across_concurrent_ops(mx_isolated):
    """Writer 1 writes; reader 2 must see the new fact within the bus RTT."""
    mx = mx_isolated
    customer = await mx.resolve("voice", "+911001001004")

    # Warm up cache.
    await mx.write(
        channel="voice", identifier="+911001001004", facts=["initial"],
    )
    await mx.read(channel="voice", identifier="+911001001004")

    # Race: writer goes first, reader immediately after (no if_version).
    res = await mx._memory.write(
        customer_id=customer.id, channel="voice", facts=["fresh fact"],
    )
    mems = await mx.read(channel="voice", identifier="+911001001004", as_text=False)
    assert any("fresh fact" in m.fact for m in mems)
    assert res.version >= 2


async def test_ledger_chain_integrity(mx_isolated):
    """Every write appends; the hash chain must verify."""
    mx = mx_isolated
    await mx.resolve("voice", "+911001001005")
    for i in range(20):
        await mx.write(
            channel="voice", identifier="+911001001005",
            facts=[f"ledger-fact-{i}"],
        )
    assert await mx.verify_ledger()


async def test_multi_user_independence(mx_isolated):
    """Writes on user A must not bump version of user B."""
    mx = mx_isolated
    ca = await mx.resolve("voice", "+911001001010")
    cb = await mx.resolve("voice", "+911001001011")

    for _ in range(5):
        await mx.write(channel="voice", identifier="+911001001010", facts=["a-fact"])

    va = await mx.current_version(customer_id=ca.id)
    vb = await mx.current_version(customer_id=cb.id)
    assert va == 5
    assert vb == 0


@pytest.mark.asyncio
async def bench_concurrent_writes(n_users: int = 200, n_writes: int = 5) -> dict:
    """Measurement: throughput + lost-write rate under wide concurrency."""
    mx = await _client("bench_conc")
    try:
        t0 = time.perf_counter()

        async def worker(uid: int) -> int:
            ident = f"+91bench{uid:06d}"
            count = 0
            for j in range(n_writes):
                try:
                    await mx.write(
                        channel="voice", identifier=ident,
                        facts=[f"u{uid}-w{j}"],
                    )
                    count += 1
                except Exception:
                    pass
            return count

        results = await asyncio.gather(*[worker(u) for u in range(n_users)])
        elapsed = time.perf_counter() - t0
        total_written = sum(results)
        expected = n_users * n_writes

        # Verify no losses.
        missed = 0
        for uid in range(n_users):
            ident = f"+91bench{uid:06d}"
            mems = await mx.read(
                channel="voice", identifier=ident, as_text=False,
            )
            stored = {m.fact for m in mems}
            for j in range(n_writes):
                if f"u{uid}-w{j}" not in stored:
                    missed += 1

        return {
            "users": n_users,
            "writes_per_user": n_writes,
            "expected": expected,
            "committed": total_written,
            "verified_in_store": expected - missed,
            "elapsed_s": round(elapsed, 3),
            "throughput_ops_s": round(expected / elapsed, 1),
            "lost_writes": missed,
            "durability": round((expected - missed) / expected, 4),
        }
    finally:
        await mx.close()


async def test_bench_runs_clean(mx_isolated):
    """Smaller sanity run of the bench inside the test suite."""
    result = await bench_concurrent_writes(n_users=20, n_writes=3)
    assert result["lost_writes"] == 0
    assert result["durability"] == 1.0
