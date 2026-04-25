"""Conflict detection accuracy."""
from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from memnex._time import utcnow
from memnex.client import Memnex
from memnex.memory import conflict as conflict_mod
from memnex.memory.models import Fact, Memory


async def run(mx: Memnex) -> dict[str, Any]:
    data = json.loads(
        files("memnex.eval.datasets").joinpath("conflicting_facts.json").read_text()
    )

    tp = fp = fn = tn = 0
    for case in data:
        existing = Memory(
            memory_id="m-existing",
            tenant_id=mx.config.tenant_id,
            customer_id="eval",
            fact=case["existing"],
            fact_type="event",
            source_channel="voice",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        incoming = Fact(fact=case["incoming"], type="event")
        conflicts = conflict_mod.detect(incoming, [existing], similarity_threshold=0.2)
        detected = bool(conflicts)
        truth = case["is_conflict"]
        if detected and truth:
            tp += 1
        elif detected and not truth:
            fp += 1
        elif not detected and truth:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "suite": "conflict",
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }
