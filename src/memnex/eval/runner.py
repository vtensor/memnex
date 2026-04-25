"""Eval orchestrator."""
from __future__ import annotations

from typing import Any

from memnex.client import Memnex
from memnex.eval.suites import conflict, handoff, identity, latency, load, recall

SUITES = {
    "identity_resolution": identity.run,
    "recall": recall.run,
    "handoff": handoff.run,
    "latency": latency.run,
    "conflict": conflict.run,
    "load": load.run,
}


async def run_suite(
    mx: Memnex,
    *,
    suite: str = "full",
    load_agents: int = 1000,
) -> dict[str, Any]:
    if suite == "full":
        out = {}
        for name, fn in SUITES.items():
            if name == "load":
                out[name] = await fn(mx, agents=load_agents)
            else:
                out[name] = await fn(mx)
        return {"results": out}

    fn = SUITES.get(suite)
    if fn is None:
        raise ValueError(f"Unknown suite: {suite}")
    if suite == "load":
        return await fn(mx, agents=load_agents)
    return await fn(mx)
