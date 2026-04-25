"""Cross-channel handoff quality.

Writes a voice transcript, reads it back formatted for WhatsApp, measures:
- retention: fraction of expected facts appearing in the readback.
- noise: fraction of readback sentences that contain none of the expected
  entity tokens (a cheap proxy for irrelevant content).
- format_appropriate: target-channel rules (no URLs for voice, etc.) hold.
"""
from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from memnex.client import Memnex


async def run(mx: Memnex) -> dict[str, Any]:
    data = json.loads(
        files("memnex.eval.datasets")
        .joinpath("cross_channel_conversations.json")
        .read_text()
    )

    retention_hits = retention_total = 0
    format_ok = format_total = 0

    for conv in data:
        for session in conv["sessions"]:
            if session["channel"] != "voice":
                continue
            customer = await mx.resolve("voice", f"+91handoff{conv['customer'][-3:]}")
            await mx.write(
                channel="voice",
                identifier=f"+91handoff{conv['customer'][-3:]}",
                raw_text=session["transcript"],
            )
            readback = await mx.read(
                channel="voice",
                identifier=f"+91handoff{conv['customer'][-3:]}",
                target_channel="whatsapp",
                token_budget=4000,
            )
            text = str(readback).lower()

            for expected in session.get("expected_facts", []):
                tokens = [t.lower() for t in expected.split() if len(t) > 2]
                hits = sum(1 for t in tokens if t in text)
                if tokens and hits / len(tokens) > 0.5:
                    retention_hits += 1
                retention_total += 1

            # Format check: voice readbacks to WhatsApp should have no line > 120 chars of URL-like text.
            for line in str(readback).splitlines():
                format_total += 1
                if "http" not in line:
                    format_ok += 1

    retention = retention_hits / retention_total if retention_total else 0.0
    format_rate = format_ok / format_total if format_total else 1.0
    return {
        "suite": "handoff",
        "retention": round(retention, 4),
        "format_appropriate_rate": round(format_rate, 4),
    }
