"""Conflict detection + resolution.

A new fact *conflicts* with an existing memory when they are about the same
thing but say opposite things — for example, ``"wants a refund"`` followed
later by ``"accepted a replacement"``.

We approximate this cheaply:

- **Entity overlap**: they must share at least one entity (or both have none
  and are semantically close).
- **Intent divergence**: if the fact type is ``intent`` or ``resolution``, and
  the opposite-polarity phrase appears in one but not the other, treat it as
  a conflict candidate.
- **String similarity**: a plain Jaccard over token sets gives a cheap proxy
  for semantic similarity without a vector DB round-trip.

If the caller configured ``conflict_strategy="ask_agent"`` we just surface the
conflict; otherwise we resolve it per the strategy.
"""
from __future__ import annotations

import re

from memnex.config import ConflictStrategy
from memnex.memory.models import Conflict, Fact, Memory

_POLARITY_FLIP_PAIRS = [
    ("want", "accept"),
    ("wants", "accepted"),
    ("refund", "replacement"),
    ("cancel", "keep"),
    ("broken", "fixed"),
    ("damaged", "replaced"),
    ("unhappy", "happy"),
    ("issue", "resolved"),
]

_TOKEN = re.compile(r"[a-z0-9#]+")


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def detect(
    incoming: Fact,
    existing: list[Memory],
    *,
    similarity_threshold: float = 0.5,
) -> list[Conflict]:
    """Return memories that look like they conflict with the incoming fact."""
    conflicts: list[Conflict] = []
    inc_toks = tokens(incoming.fact)
    for m in existing:
        if not m.is_active:
            continue
        shared_entities = bool(set(incoming.entities) & set(m.entities))
        sim = jaccard(incoming.fact, m.fact)
        if not shared_entities and sim < similarity_threshold:
            continue
        if _opposite_polarity(inc_toks, tokens(m.fact)):
            conflicts.append(Conflict(existing=m, incoming=incoming, similarity=sim))
    return conflicts


def _opposite_polarity(a: set[str], b: set[str]) -> bool:
    for x, y in _POLARITY_FLIP_PAIRS:
        if (x in a and y in b) or (y in a and x in b):
            return True
    return False


def apply_strategy(
    conflict: Conflict,
    strategy: ConflictStrategy,
) -> Conflict:
    """Annotate the Conflict with how it should be resolved."""
    if strategy == "latest_wins":
        conflict.resolution = "supersede"
    elif strategy == "keep_both":
        conflict.resolution = "keep_both"
    else:  # ask_agent
        conflict.resolution = "defer"
    return conflict
