"""Latency percentile benchmark."""
from __future__ import annotations

import statistics
import time
from typing import Any

from memnex.client import Memnex


async def run(mx: Memnex, iterations: int = 500) -> dict[str, Any]:
    # Seed one customer.
    customer = await mx.resolve("voice", "+91latency0001")
    await mx.write(
        channel="voice",
        identifier="+91latency0001",
        facts=["Order #99 is in transit", "Customer prefers email updates"],
    )

    write_latencies: list[float] = []
    read_latencies: list[float] = []
    resolve_latencies: list[float] = []

    for i in range(iterations):
        t0 = time.perf_counter()
        await mx.write(
            channel="voice",
            identifier="+91latency0001",
            facts=[f"Event #{i} happened"],
        )
        write_latencies.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        await mx.read(channel="voice", identifier="+91latency0001", target_channel="whatsapp")
        read_latencies.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        await mx.resolve("voice", "+91latency0001")
        resolve_latencies.append((time.perf_counter() - t0) * 1000)

    return {
        "suite": "latency",
        "iterations": iterations,
        "write_ms": _percentiles(write_latencies),
        "read_ms": _percentiles(read_latencies),
        "resolve_ms": _percentiles(resolve_latencies),
        "customer_id": customer.id,
    }


def _percentiles(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_s = sorted(samples)
    return {
        "p50": round(statistics.median(sorted_s), 2),
        "p95": round(sorted_s[int(0.95 * len(sorted_s))], 2),
        "p99": round(sorted_s[min(int(0.99 * len(sorted_s)), len(sorted_s) - 1)], 2),
        "mean": round(statistics.mean(sorted_s), 2),
    }
