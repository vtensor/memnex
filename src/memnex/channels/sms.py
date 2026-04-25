"""SMS adapter — extremely concise, no markdown."""
from __future__ import annotations

from typing import Any

from memnex.channels.base import BaseChannelAdapter, _time_ago, register
from memnex.memory.models import Memory


@register
class SMSChannelAdapter(BaseChannelAdapter):
    channel = "sms"

    def extract(self, raw: Any, metadata: dict | None = None) -> str:
        return raw if isinstance(raw, str) else str(raw)

    def format(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        last = max(memories, key=lambda m: m.created_at)
        top = sorted(memories, key=lambda m: m.salience, reverse=True)[:2]
        facts = "; ".join(m.fact for m in top)
        return f"Prev ({last.source_channel}, {_time_ago(last.created_at)}): {facts}"
