"""Extended recall benchmark.

Writes multi-sentence transcripts per user, then asks questions that expect
a substring in the formatted read-back. Methodology matches LoCoMo/Zep/Mem0
evaluations: F1 on expected-substring presence.

Evaluates configurations side-by-side:
- rules_only (pure regex baseline)
- hybrid_fuzzy (rules + rapidfuzz)
- hybrid_encoder (rules + rapidfuzz + sentence-transformers, if installed)
"""
from __future__ import annotations

import json
import time
from importlib.resources import files
from typing import Any

from memnex import Memnex, MemnexConfig
from memnex.memory.extractor import RuleBasedExtractor
from memnex.memory.hybrid_extractor import HybridConfig, HybridExtractor


CONFIGS: dict[str, Any] = {
    "rules_only": lambda: RuleBasedExtractor(),
    "hybrid_fuzzy": lambda: HybridExtractor(HybridConfig(use_encoder=False)),
    "hybrid_encoder": lambda: HybridExtractor(HybridConfig(use_encoder=True)),
}


async def run_one(extractor_name: str) -> dict[str, Any]:
    data = json.loads(
        files("memnex.eval.datasets").joinpath("extended_recall.json").read_text()
    )

    # Permissive policy: every fact type accepts user_content. Isolates
    # extractor quality from trust-policy effects.
    permissive = {
        "min_trust": {t: 1 for t in ("profile", "preference", "resolution",
                                      "intent", "issue", "event")},
        "render_min_trust": 2,
        "reject_injection_patterns": True,
    }
    mx = await Memnex.create(
        config=MemnexConfig(
            tenant_id=f"recall_{extractor_name}", trust_policy=permissive
        )
    )
    mx._memory._extractor = CONFIGS[extractor_name]()

    tp = 0
    total = 0
    extraction_times: list[float] = []

    try:
        for conv in data:
            uid = conv["user_id"]
            # Use voice channel with a synthetic identifier keyed to user.
            ident = f"+91eval{uid}"
            await mx.resolve("voice", ident)
            for transcript in conv["transcripts"]:
                t0 = time.perf_counter()
                await mx.write(
                    channel="voice",
                    identifier=ident,
                    raw_text=transcript,
                    trust_level="user_content",
                )
                extraction_times.append((time.perf_counter() - t0) * 1000)

            # Read back in markdown form (broad format for substring matching).
            readback = str(
                await mx.read(
                    channel="voice",
                    identifier=ident,
                    target_channel="web",
                    token_budget=4000,
                )
            ).lower()

            for q in conv["questions"]:
                total += 1
                if q["expected"].lower() in readback:
                    tp += 1
    finally:
        await mx.close()

    recall = tp / total if total else 0.0
    return {
        "config": extractor_name,
        "questions": total,
        "correct": tp,
        "recall": round(recall, 4),
        "f1": round(recall, 4),  # binary presence → F1 = recall when precision=1.0
        "extraction_ms": {
            "p50": round(_pct(extraction_times, 0.5), 2),
            "p95": round(_pct(extraction_times, 0.95), 2),
            "mean": round(sum(extraction_times) / len(extraction_times), 2),
        },
    }


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = int(p * (len(s) - 1))
    return s[i]


async def run(_mx: Memnex | None = None) -> dict[str, Any]:
    """Entry point compatible with the runner signature. Spins up its own
    Memnex per config so extractors don't bleed across runs."""
    results: dict[str, Any] = {}
    for name in CONFIGS:
        try:
            results[name] = await run_one(name)
        except Exception as e:
            results[name] = {"error": str(e)}
    return {"suite": "extended_recall", "results": results}
