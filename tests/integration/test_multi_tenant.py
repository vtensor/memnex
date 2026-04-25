from memnex import Memnex, MemnexConfig


async def test_tenants_cannot_see_each_other():
    a = await Memnex.create(config=MemnexConfig(tenant_id="tenant_a"))
    b = await Memnex.create(config=MemnexConfig(tenant_id="tenant_b"))
    try:
        # Tenant A writes a memory for a phone number.
        await a.resolve("voice", "+91 92410 63955")
        await a.write(
            channel="voice", identifier="+91 92410 63955",
            facts=["Secret A: tenant A knows this"],
        )

        # Tenant B uses the same phone number — they must get a fresh customer
        # and never see tenant A's memories.
        await b.resolve("voice", "+91 92410 63955")
        ctx = await b.read(
            channel="voice", identifier="+91 92410 63955",
            target_channel="whatsapp",
        )
        assert "Secret A" not in ctx
    finally:
        await a.close()
        await b.close()
