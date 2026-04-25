async def test_write_then_read_roundtrip(mx_isolated):
    customer = await mx_isolated.resolve("voice", "+91 92410 63955")
    await mx_isolated.write(
        channel="voice",
        identifier="+91 92410 63955",
        facts=["Order #4521 arrived damaged", "Customer wants a refund"],
    )
    readback = await mx_isolated.read(
        channel="voice", identifier="+91 92410 63955", target_channel="whatsapp"
    )
    assert "4521" in readback
    assert "refund" in readback.lower()


async def test_write_drops_low_salience_greetings(mx_isolated):
    await mx_isolated.resolve("voice", "+91 92410 63955")
    written = await mx_isolated.write(
        channel="voice",
        identifier="+91 92410 63955",
        raw_text="Hi. Thanks for your time.",
    )
    # All greeting/filler — should yield nothing or only low-value facts.
    for m in written:
        assert m.salience >= 0.1


async def test_conflict_supersedes_old_fact(mx_isolated):
    await mx_isolated.resolve("voice", "+91 92410 63955")
    first = await mx_isolated.write(
        channel="voice",
        identifier="+91 92410 63955",
        facts=["Customer wants a refund for order #4521"],
    )
    await mx_isolated.write(
        channel="voice",
        identifier="+91 92410 63955",
        facts=["Customer accepted a replacement for order #4521"],
    )
    memories = await mx_isolated.read(
        channel="voice", identifier="+91 92410 63955", as_text=False
    )
    mids = {m.memory_id for m in memories}
    # The superseded memory should no longer appear in active reads.
    assert first[0].memory_id not in mids


async def test_search_returns_relevant(mx_isolated):
    await mx_isolated.resolve("voice", "+91 92410 63955")
    await mx_isolated.write(
        channel="voice",
        identifier="+91 92410 63955",
        facts=[
            "Order #4521 arrived damaged",
            "Customer prefers morning calls",
            "Refund processed via UPI",
        ],
    )
    results = await mx_isolated.search(
        channel="voice", identifier="+91 92410 63955",
        query="damaged order", max_results=2,
    )
    assert results
