"""Memory recall accuracy, LoCoMo-style.

For each multi-session conversation:
  1. Write every session's transcript into Memnex.
  2. For each handoff question, check whether the expected substring appears
     in the formatted read-back for the target channel.
F1 is computed across all questions.
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

    tp = fp = fn = 0
    for conv in data:
        first = conv["sessions"][0]
        customer = await mx.resolve("voice", "+9199000" + conv["customer"][-4:])
        for session in conv["sessions"]:
            await mx.link_identity(
                customer_id=customer.id,
                channel=session["channel"],
                identifier=f"{session['channel']}:eval:{customer.id}",
            )
            transcript = session["transcript"]
            if isinstance(transcript, list):
                await mx.write(
                    channel=session["channel"],
                    identifier=f"{session['channel']}:eval:{customer.id}",
                    raw_text="\n".join(
                        m.get("content", "") for m in transcript
                    ),
                )
            else:
                await mx.write(
                    channel=session["channel"],
                    identifier=f"{session['channel']}:eval:{customer.id}",
                    raw_text=transcript,
                )

        readback = await mx.read(
            channel=first["channel"],
            identifier=f"{first['channel']}:eval:{customer.id}",
            target_channel="whatsapp",
            token_budget=4000,
        )
        ctx_lower = str(readback).lower()
        for q in conv["handoff_questions"]:
            if q["expected"].lower() in ctx_lower:
                tp += 1
            else:
                fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "suite": "recall",
        "questions": tp + fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
