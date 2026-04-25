"""Trace which stored memories were used to produce a piece of agent output.

Approach: for every memory we returned in the most recent read, check if a
non-trivial substring of the memory's fact appears in the agent's output.

This is lossy (an LLM can paraphrase), but useful in practice: it catches
verbatim or near-verbatim quotes, and flags when the agent's output cannot
be traced to any stored memory (potential hallucination).

For robustness against paraphrase, we also fall back to a token-Jaccard
overlap with a configurable threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from memnex.memory.models import Memory

_TOK = re.compile(r"[a-z0-9#]+")


@dataclass
class TraceHit:
    memory_id: str
    fact: str
    match_type: str            # "substring" | "jaccard"
    score: float               # 1.0 for substring, 0..1 for jaccard


def _tokens(text: str) -> set[str]:
    return {t for t in _TOK.findall(text.lower()) if len(t) > 2}


def trace_output(
    agent_output: str,
    candidate_memories: list[Memory],
    *,
    min_substring_len: int = 15,
    jaccard_threshold: float = 0.35,
) -> list[TraceHit]:
    """Return the subset of memories the output can be traced back to.

    Empty result = the output could not be attributed to any stored memory.
    That is an alarm signal: the agent may have hallucinated, or the
    retrieval pipeline missed a source.
    """
    if not agent_output.strip():
        return []

    out_lower = agent_output.lower()
    out_tokens = _tokens(agent_output)
    hits: list[TraceHit] = []

    for m in candidate_memories:
        fact_lower = m.fact.lower()
        # 1) Exact substring. Try shrinking from the full fact down to
        #    min_substring_len chars from the middle.
        if len(fact_lower) >= min_substring_len and fact_lower in out_lower:
            hits.append(TraceHit(m.memory_id, m.fact, "substring", 1.0))
            continue
        # Longest common phrase of length >= min_substring_len.
        for n in range(len(fact_lower), min_substring_len - 1, -1):
            for i in range(0, len(fact_lower) - n + 1):
                piece = fact_lower[i : i + n]
                if piece in out_lower:
                    hits.append(
                        TraceHit(m.memory_id, m.fact, "substring", n / len(fact_lower))
                    )
                    break
            else:
                continue
            break

        # 2) Token Jaccard fallback for paraphrases.
        fact_tokens = _tokens(m.fact)
        if not fact_tokens or not out_tokens:
            continue
        inter = len(fact_tokens & out_tokens)
        union = len(fact_tokens | out_tokens)
        j = inter / union if union else 0.0
        if j >= jaccard_threshold:
            hits.append(TraceHit(m.memory_id, m.fact, "jaccard", round(j, 3)))

    # Dedupe by memory_id keeping best score.
    best: dict[str, TraceHit] = {}
    for h in hits:
        prev = best.get(h.memory_id)
        if prev is None or h.score > prev.score:
            best[h.memory_id] = h
    return sorted(best.values(), key=lambda h: h.score, reverse=True)
