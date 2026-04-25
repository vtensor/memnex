"""Identity resolution benchmark.

Feeds the synthetic dataset into a fresh tenant, then verifies that every
channel identifier resolves back to the expected customer id. Reports
precision, recall, F1.
"""
from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from memnex.client import Memnex


async def run(mx: Memnex) -> dict[str, Any]:
    data = json.loads(
        files("memnex.eval.datasets").joinpath("synthetic_identities.json").read_text()
    )
    expected: dict[tuple[str, str], str] = {}
    for record in data:
        first = record["identifiers"][0]
        customer = await mx.resolve(first["channel"], first["identifier"])
        expected[(first["channel"], first["identifier"])] = customer.id
        for ident in record["identifiers"][1:]:
            await mx.link_identity(
                customer_id=customer.id,
                channel=ident["channel"],
                identifier=ident["identifier"],
            )
            expected[(ident["channel"], ident["identifier"])] = customer.id

    tp = fp = fn = 0
    for record in data:
        for ident in record["identifiers"]:
            want = expected[(ident["channel"], ident["identifier"])]
            try:
                got = await mx.resolve(
                    ident["channel"], ident["identifier"], auto_create=False
                )
                if got.id == want:
                    tp += 1
                else:
                    fp += 1
            except KeyError:
                fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "suite": "identity_resolution",
        "cases": tp + fp + fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
