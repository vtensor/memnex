import pytest

from memnex.memory.extractor import RuleBasedExtractor


@pytest.mark.asyncio
async def test_extractor_drops_greetings_and_fillers():
    ext = RuleBasedExtractor()
    text = "Hi. Um, my order #4521 is damaged. I want a refund. Thanks."
    facts = await ext.extract(text, channel="voice")
    fact_texts = [f.fact for f in facts]
    assert any("4521" in f for f in fact_texts)
    assert any("refund" in f.lower() for f in fact_texts)
    # Greetings/thanks dropped.
    assert not any(f.lower().startswith(("hi", "thanks")) for f in fact_texts)


@pytest.mark.asyncio
async def test_extractor_classifies_intents_and_issues():
    ext = RuleBasedExtractor()
    facts = await ext.extract(
        "My order #4521 is broken. I want a refund.", channel="voice"
    )
    types = {f.type for f in facts}
    assert "issue" in types
    assert "intent" in types


@pytest.mark.asyncio
async def test_extractor_extracts_order_entities():
    ext = RuleBasedExtractor()
    facts = await ext.extract("My order #4521 broke.", channel="voice")
    assert any("order_4521" in f.entities for f in facts)
