"""Concurrent-write load test. Reports throughput at increasing concurrency."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from memnex.client import Memnex


async def run(mx: Memnex, agents: int = 1000) -> dict[str, Any]:
    async def _one(i: int) -> None:
        ident = f"+91load{i:08d}"
        await mx.write(
            channel="voice",
            identifier=ident,
            facts=[f"Event {i}", f"Customer {i} has an issue"],
        )
        await mx.read(channel="voice", identifier=ident, target_channel="whatsapp")

    t0 = time.perf_counter()
    await asyncio.gather(*[_one(i) for i in range(agents)])
    elapsed = time.perf_counter() - t0

    return {
        "suite": "load",
        "agents": agents,
        "elapsed_s": round(elapsed, 2),
        "throughput_ops_s": round((agents * 2) / elapsed, 1),  # 2 ops per agent
    }
