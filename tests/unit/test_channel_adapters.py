from datetime import datetime

from memnex.channels.base import get_adapter
from memnex.memory.models import Memory


def _m(fact: str, ftype: str = "issue", channel: str = "voice") -> Memory:
    now = datetime.utcnow()
    return Memory(
        memory_id="m-" + fact[:4],
        tenant_id="t",
        customer_id="c",
        fact=fact,
        fact_type=ftype,
        source_channel=channel,
        created_at=now,
        updated_at=now,
        salience=0.9,
    )


def test_voice_adapter_strips_fillers():
    adapter = get_adapter("voice")
    cleaned = adapter.extract("Um, my order, my order number is 4521.")
    assert "Um" not in cleaned
    assert "my order, my order" not in cleaned


def test_voice_adapter_format_has_no_urls():
    adapter = get_adapter("voice")
    memories = [_m("See https://example.com/o/4521 for damage photo", "issue")]
    out = adapter.format(memories)
    assert "http" not in out


def test_whatsapp_adapter_bullet_format():
    adapter = get_adapter("whatsapp")
    memories = [_m("Order #4521 damaged", "issue"), _m("Wants refund", "intent")]
    out = adapter.format(memories)
    assert out.startswith("Previous interaction")
    assert "- Issue:" in out


def test_web_adapter_groups_by_type():
    adapter = get_adapter("web")
    memories = [_m("Order #4521 damaged", "issue"), _m("Wants refund", "intent")]
    out = adapter.format(memories)
    assert "**Issue**" in out
    assert "**Intent**" in out


def test_sms_adapter_is_short():
    adapter = get_adapter("sms")
    memories = [_m("Order #4521 damaged", "issue")]
    out = adapter.format(memories)
    assert len(out) < 160  # SMS-friendly
