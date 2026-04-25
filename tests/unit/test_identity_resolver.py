import pytest


async def test_resolve_creates_customer_once(mx_isolated):
    a = await mx_isolated.resolve("voice", "+91 92410 63955")
    b = await mx_isolated.resolve("voice", "+919241063955")
    assert a.id == b.id  # same normalized identifier


async def test_link_across_channels(mx_isolated):
    customer = await mx_isolated.resolve("voice", "+91 92410 63955")
    await mx_isolated.link_identity(
        customer_id=customer.id, channel="whatsapp", identifier="wa:919241063955"
    )
    via_wa = await mx_isolated.resolve("whatsapp", "wa:919241063955")
    assert via_wa.id == customer.id


async def test_check_match_same_person(mx_isolated):
    customer = await mx_isolated.resolve("voice", "+91 92410 63955")
    await mx_isolated.link_identity(
        customer_id=customer.id, channel="web", identifier="sess_abc"
    )
    match = await mx_isolated.check_match(
        ("voice", "+919241063955"), ("web", "sess_abc")
    )
    assert match.is_same
    assert match.confidence == 1.0


async def test_check_match_different_people(mx_isolated):
    await mx_isolated.resolve("voice", "+919241063955")
    await mx_isolated.resolve("voice", "+918765432100")
    match = await mx_isolated.check_match(
        ("voice", "+919241063955"), ("voice", "+918765432100")
    )
    assert not match.is_same


async def test_resolve_auto_create_false_raises_on_miss(mx_isolated):
    with pytest.raises(KeyError):
        await mx_isolated.resolve("voice", "+91999999999", auto_create=False)
