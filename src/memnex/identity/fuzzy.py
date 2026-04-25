"""Fuzzy identity matching.

Used when deterministic resolution fails but the signals suggest two
identifiers might belong to the same person. The matcher only returns a
*candidate* — the caller is expected to surface it for confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from memnex.identity.models import Customer


@dataclass
class FuzzyCandidate:
    customer_id: str
    confidence: float
    evidence: dict


def name_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    a_tokens = {t.lower() for t in a.split() if t}
    b_tokens = {t.lower() for t in b.split() if t}
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return inter / union


def find_candidates(
    candidates: list[Customer],
    *,
    new_name: str | None,
    new_topic: str | None,
    now: datetime,
    window_hours: int = 24,
) -> list[FuzzyCandidate]:
    """Rank existing customers as possible matches for a new identity.

    Signals:
    - Name token overlap between stored metadata and the new name.
    - Recent activity: customer seen within ``window_hours``.
    - Topic overlap (if a topic is supplied).
    """
    out: list[FuzzyCandidate] = []
    window = timedelta(hours=window_hours)
    for c in candidates:
        evidence: dict = {}
        score = 0.0

        stored_name = c.metadata.get("name") if c.metadata else None
        name_score = name_similarity(new_name, stored_name)
        if name_score > 0:
            evidence["name_similarity"] = name_score
            score += 0.6 * name_score

        if c.last_seen_at and now - c.last_seen_at < window:
            evidence["recent_activity_hours"] = (now - c.last_seen_at).total_seconds() / 3600
            score += 0.3

        if new_topic and c.metadata:
            stored_topic = c.metadata.get("last_topic")
            if stored_topic and _topic_overlap(new_topic, stored_topic):
                evidence["topic_overlap"] = True
                score += 0.1

        if score >= 0.5:
            out.append(FuzzyCandidate(
                customer_id=c.id, confidence=min(score, 0.95), evidence=evidence
            ))

    out.sort(key=lambda x: x.confidence, reverse=True)
    return out


def _topic_overlap(a: str, b: str) -> bool:
    a_tokens = {t.lower() for t in a.split() if len(t) > 3}
    b_tokens = {t.lower() for t in b.split() if len(t) > 3}
    if not a_tokens or not b_tokens:
        return False
    return bool(a_tokens & b_tokens)
