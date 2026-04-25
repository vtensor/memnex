"""Salience scoring.

Each fact gets a 0.0-1.0 score. Facts below the config threshold are dropped
immediately. Scoring is deterministic and rule-based — a real deployment
might swap in a learned model, which is why it lives behind a single function.

Formula (matches the blueprint):
    salience = 0.30*specificity
             + 0.25*actionability
             + 0.20*recency
             + 0.15*emotional_weight
             + 0.10*uniqueness
"""
from __future__ import annotations

import re

from memnex.memory.models import Fact, FactType

_SPECIFIC_MARKERS = re.compile(r"\b(\d+|#\w+|₹|\$|€|order|ticket|invoice|date)\b", re.IGNORECASE)
_ACTIONABLE_TYPES: set[FactType] = {"intent", "issue", "resolution"}
_EMOTIONAL = re.compile(
    r"\b(angry|frustrat|happy|delight|upset|annoy|thrill|love|hate|sad)\w*",
    re.IGNORECASE,
)


def score(fact: Fact, *, recency: float = 1.0, uniqueness: float = 1.0) -> float:
    """Score a single fact. ``recency`` and ``uniqueness`` are 0.0-1.0 signals.

    Callers pass ``recency=1.0`` for just-extracted facts (default).
    ``uniqueness`` is 1.0 when the fact is novel for this customer.
    """
    specificity = _specificity(fact)
    actionability = 1.0 if fact.type in _ACTIONABLE_TYPES else 0.4
    emotional = 1.0 if _EMOTIONAL.search(fact.fact) else 0.2

    s = (
        0.30 * specificity
        + 0.25 * actionability
        + 0.20 * recency
        + 0.15 * emotional
        + 0.10 * uniqueness
    )
    # Confidence boost: low-confidence extractions are inherently less salient.
    return round(min(s * (0.5 + 0.5 * fact.confidence), 1.0), 4)


def _specificity(fact: Fact) -> float:
    s = 0.3
    if fact.entities:
        s += 0.35
    if _SPECIFIC_MARKERS.search(fact.fact):
        s += 0.25
    if len(fact.fact.split()) >= 8:
        s += 0.1
    return min(s, 1.0)
