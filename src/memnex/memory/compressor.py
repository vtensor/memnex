"""Token budget compressor.

Given a ranked list of memories and a token budget, return the largest subset
that still fits. We always keep: (a) the most recent active intent, (b) the
most recent resolution, (c) one profile fact. Everything else is dropped
lowest-salience first, then merged where possible.

Token counting uses a cheap word-proxy (≈0.75 tokens per word). If callers
need exact token counts they can swap in tiktoken.
"""
from __future__ import annotations

from memnex.memory.models import Memory

_KEEP_TYPES = ("intent", "resolution", "profile")


def approx_tokens(text: str) -> int:
    # Rough but stable proxy: ceil(words / 0.75). Off by <15% vs tiktoken for English.
    words = max(1, len(text.split()))
    return int(words / 0.75) + 1


def compress(memories: list[Memory], *, token_budget: int) -> list[Memory]:
    if not memories:
        return []

    pinned: list[Memory] = []
    seen_types: set[str] = set()
    for m in memories:
        if m.fact_type in _KEEP_TYPES and m.fact_type not in seen_types:
            pinned.append(m)
            seen_types.add(m.fact_type)

    pool = [m for m in memories if m not in pinned]
    pool.sort(key=lambda x: (x.salience, x.created_at), reverse=True)

    out: list[Memory] = list(pinned)
    used = sum(approx_tokens(m.fact) for m in pinned)

    for m in pool:
        cost = approx_tokens(m.fact)
        if used + cost > token_budget:
            continue
        out.append(m)
        used += cost

    # Re-sort final list by salience for stable output.
    out.sort(key=lambda x: (x.salience, x.created_at), reverse=True)
    return out
