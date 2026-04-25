async def test_forget_customer_total_purge(mx_isolated):
    mx = mx_isolated
    c = await mx.resolve("voice", "+91 92410 63955")
    await mx.write(channel="voice", identifier="+91 92410 63955",
                   facts=["Some memory"])

    receipt = await mx.forget_customer(customer_id=c.id, reason="gdpr_request")
    assert receipt["deleted"]["customers"] == 1
    assert receipt["deleted"]["memories"] >= 1
    assert "receipt_hash" in receipt

    # After forgetting, resolve with auto_create=False must fail.
    import pytest
    with pytest.raises(KeyError):
        await mx.resolve("voice", "+91 92410 63955", auto_create=False)


async def test_export_customer_data(mx_isolated):
    mx = mx_isolated
    c = await mx.resolve("voice", "+91 92410 63955")
    await mx.write(channel="voice", identifier="+91 92410 63955",
                   facts=["A fact to export"])

    data = await mx.export_customer_data(customer_id=c.id)
    assert data["customer"]["id"] == c.id
    assert any("export" in m["fact"] for m in data["memories"])


async def test_ttl_memories_expire(mx_isolated):
    mx = mx_isolated
    from datetime import datetime, timedelta

    c = await mx.resolve("voice", "+91 92410 63955")
    written = await mx.write(
        channel="voice", identifier="+91 92410 63955",
        facts=["Temporary OTP 483921"], ttl_hours=1,
    )
    assert written
    # Manually advance expiry by mutating the warm store directly.
    warm = mx._stores.warm
    for m in warm._memories.values():
        object.__setattr__(
            m, "expires_at", datetime.utcnow() - timedelta(hours=1)
        )

    from memnex.privacy.ttl import enforce
    n = await enforce(warm)
    assert n == len(written)
