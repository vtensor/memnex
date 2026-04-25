"""Audit layer tests (C-pillar).

- Every write returns a tamper-evident receipt.
- The trace function correctly attributes agent output to source memories.
- Hallucination (output with no source) returns an empty trace (alarm).
"""
from __future__ import annotations

import pytest

from memnex import Memnex, MemnexConfig
from memnex.audit.receipts import sign_receipt, verify_receipt
from memnex.audit.trace import trace_output


async def test_write_returns_signed_receipt(mx_isolated):
    mx = mx_isolated
    await mx.resolve("voice", "+912001001001")
    res = await mx._memory.write(
        customer_id=(await mx.resolve("voice", "+912001001001")).id,
        channel="voice",
        facts=["Order #4521 arrived damaged"],
    )
    receipt = res.receipt
    assert receipt is not None
    assert receipt["op"] == "write"
    assert receipt["payload"]["version"] == res.version
    assert verify_receipt(receipt)


async def test_receipt_tamper_is_detected():
    receipt = sign_receipt(
        op="write", tenant_id="t", customer_id="c",
        payload={"memory_ids": ["m1", "m2"], "version": 1},
    ).to_dict()
    assert verify_receipt(receipt)

    # Tamper with payload.
    tampered = dict(receipt)
    tampered["payload"] = {"memory_ids": ["EVIL"], "version": 1}
    assert not verify_receipt(tampered)


async def test_trace_finds_verbatim_quote(mx_isolated):
    mx = mx_isolated
    await mx.resolve("voice", "+912001001002")
    await mx.write(
        channel="voice", identifier="+912001001002",
        facts=["Order #4521 arrived damaged last week"],
    )

    agent_output = (
        "According to our records, order #4521 arrived damaged last week. "
        "I'd be happy to process a refund for you."
    )
    hits = await mx.trace_output(
        channel="voice", identifier="+912001001002",
        agent_output=agent_output,
    )
    assert hits, "verbatim quote should be traceable"
    assert hits[0]["match_type"] == "substring"
    assert hits[0]["score"] > 0.5


async def test_trace_finds_paraphrase_via_jaccard(mx_isolated):
    mx = mx_isolated
    await mx.resolve("voice", "+912001001003")
    await mx.write(
        channel="voice", identifier="+912001001003",
        facts=["Customer wants a refund for order 4521"],
    )

    # Paraphrased but same content tokens.
    agent_output = "The customer has requested a refund on order 4521."
    hits = await mx.trace_output(
        channel="voice", identifier="+912001001003",
        agent_output=agent_output,
    )
    assert hits, "paraphrase should be traceable via token jaccard"


async def test_hallucination_returns_empty_trace(mx_isolated):
    mx = mx_isolated
    await mx.resolve("voice", "+912001001004")
    await mx.write(
        channel="voice", identifier="+912001001004",
        facts=["Order #4521 arrived damaged"],
    )

    # Agent output completely unrelated to stored memories.
    hallucinated = "The customer's credit card balance is 50,000 rupees and they live in Pune."
    hits = await mx.trace_output(
        channel="voice", identifier="+912001001004",
        agent_output=hallucinated,
    )
    assert hits == [], "hallucination must not be attributable"


async def test_ledger_chain_and_receipt_together(mx_isolated):
    """Receipts reference the ledger; ledger chain must verify too."""
    mx = mx_isolated
    await mx.resolve("voice", "+912001001005")
    first = await mx._memory.write(
        customer_id=(await mx.resolve("voice", "+912001001005")).id,
        channel="voice", facts=["fact one"],
    )
    second = await mx._memory.write(
        customer_id=(await mx.resolve("voice", "+912001001005")).id,
        channel="voice", facts=["fact two"],
    )
    # Receipts reference distinct ledger seqs.
    assert first.receipt["payload"]["ledger_seq"] != second.receipt["payload"]["ledger_seq"]
    # Chain verifies.
    assert await mx.verify_ledger()


# ---- benchmark ---------------------------------------------------------
async def bench_trace_accuracy() -> dict:
    """Measurement: trace recall on verbatim + paraphrased + hallucinated."""
    mx = await Memnex.create(config=MemnexConfig(tenant_id="trace_bench"))
    try:
        cases = [
            {
                "memory": "Order #4521 arrived damaged",
                "output": "I see that order #4521 arrived damaged.",
                "kind": "verbatim",
                "should_trace": True,
            },
            {
                "memory": "Customer wants a refund",
                "output": "The customer is requesting a refund.",
                "kind": "paraphrase",
                "should_trace": True,
            },
            {
                "memory": "Prefers morning calls",
                "output": "The user prefers to be called in the morning.",
                "kind": "paraphrase",
                "should_trace": True,
            },
            {
                "memory": "Order arrived damaged",
                "output": "The user's credit score improved this quarter.",
                "kind": "unrelated",
                "should_trace": False,
            },
        ]

        correct = 0
        for i, c in enumerate(cases):
            ident = f"+9120020{i:07d}"
            await mx.resolve("voice", ident)
            await mx.write(channel="voice", identifier=ident, facts=[c["memory"]])
            hits = await mx.trace_output(
                channel="voice", identifier=ident, agent_output=c["output"],
            )
            traced = bool(hits)
            if traced == c["should_trace"]:
                correct += 1

        return {
            "cases": len(cases),
            "correct": correct,
            "accuracy": round(correct / len(cases), 4),
        }
    finally:
        await mx.close()


async def test_bench_trace_accuracy():
    result = await bench_trace_accuracy()
    assert result["accuracy"] >= 0.75, result
