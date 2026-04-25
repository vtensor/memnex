from datetime import datetime

from memnex.memory import conflict
from memnex.memory.models import Fact, Memory


def _memory(text: str, entities: list[str] | None = None) -> Memory:
    now = datetime.utcnow()
    return Memory(
        memory_id="m1",
        tenant_id="t",
        customer_id="c",
        fact=text,
        fact_type="intent",
        entities=entities or [],
        source_channel="voice",
        created_at=now,
        updated_at=now,
    )


def test_detects_refund_vs_replacement_conflict():
    existing = _memory("Customer wants a refund for order #4521", ["order_4521"])
    incoming = Fact(fact="Customer accepted a replacement for order #4521",
                    type="resolution", entities=["order_4521"])
    assert conflict.detect(incoming, [existing], similarity_threshold=0.2)


def test_no_conflict_for_unrelated_facts():
    existing = _memory("Order #1111 is delayed", ["order_1111"])
    incoming = Fact(fact="Order #2222 arrived", type="event", entities=["order_2222"])
    assert not conflict.detect(incoming, [existing], similarity_threshold=0.5)


def test_latest_wins_resolution():
    existing = _memory("Customer wants a refund", [])
    incoming = Fact(fact="Customer accepted a replacement", type="resolution")
    conflicts = conflict.detect(incoming, [existing], similarity_threshold=0.2)
    assert conflicts
    resolved = conflict.apply_strategy(conflicts[0], "latest_wins")
    assert resolved.resolution == "supersede"


def test_keep_both_resolution():
    existing = _memory("Customer wants a refund", [])
    incoming = Fact(fact="Customer accepted a replacement", type="resolution")
    conflicts = conflict.detect(incoming, [existing], similarity_threshold=0.2)
    assert conflicts
    resolved = conflict.apply_strategy(conflicts[0], "keep_both")
    assert resolved.resolution == "keep_both"
