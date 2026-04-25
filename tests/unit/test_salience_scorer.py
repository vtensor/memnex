from memnex.memory.models import Fact
from memnex.memory.salience import score


def test_actionable_facts_score_higher_than_filler():
    action = Fact(fact="Customer wants a refund for order #4521",
                  type="intent", entities=["order_4521"], confidence=0.95)
    filler = Fact(fact="Hi there", type="event", entities=[], confidence=0.5)
    assert score(action) > score(filler)


def test_entity_presence_boosts_specificity():
    with_ent = Fact(fact="Order #4521 is damaged", type="issue", entities=["order_4521"])
    without = Fact(fact="Order is damaged", type="issue", entities=[])
    assert score(with_ent) >= score(without)


def test_emotional_weight_contributes():
    frustrated = Fact(fact="Customer is angry about order 4521",
                      type="issue", entities=["order_4521"])
    neutral = Fact(fact="Customer checked order 4521",
                   type="event", entities=["order_4521"])
    assert score(frustrated) > score(neutral)


def test_score_bounded():
    f = Fact(fact="x", type="event")
    s = score(f)
    assert 0.0 <= s <= 1.0
