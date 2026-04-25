"""The hero test: voice call, then WhatsApp, then web — the agent on every
channel must see what happened on the previous ones."""


async def test_voice_to_whatsapp_to_web(mx_isolated):
    mx = mx_isolated

    customer = await mx.resolve("voice", "+91 92410 63955")

    await mx.write(
        channel="voice",
        identifier="+91 92410 63955",
        facts=[
            "Order #4521 arrived damaged",
            "Customer wants a full refund",
            "Customer has been with us for 3 years",
        ],
        session_id="call_abc123",
    )

    await mx.link_identity(
        customer_id=customer.id, channel="whatsapp", identifier="wa:919241063955"
    )
    await mx.link_identity(
        customer_id=customer.id, channel="web", identifier="sess_abc123"
    )

    wa_context = await mx.read(
        channel="whatsapp", identifier="wa:919241063955",
        target_channel="whatsapp", token_budget=2000,
    )
    assert "4521" in wa_context
    assert "refund" in wa_context.lower()

    web_context = await mx.read(
        channel="web", identifier="sess_abc123",
        target_channel="web", token_budget=2000,
    )
    assert "**Issue**" in web_context
    assert "4521" in web_context


async def test_same_customer_same_timeline(mx_isolated):
    mx = mx_isolated
    c = await mx.resolve("voice", "+91 92410 63955")
    await mx.write(channel="voice", identifier="+91 92410 63955",
                   facts=["Order #4521 damaged"])
    await mx.link_identity(customer_id=c.id, channel="whatsapp",
                           identifier="wa:919241063955")
    await mx.write(channel="whatsapp", identifier="wa:919241063955",
                   facts=["Customer shared damage photo"])
    timeline = await mx.get_timeline(customer_id=c.id)
    assert len(timeline) == 2
    assert timeline[0].source_channel == "voice"
    assert timeline[1].source_channel == "whatsapp"
