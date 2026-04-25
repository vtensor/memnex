"""WhatsApp channel adapter."""
from __future__ import annotations

from typing import Any

from memnex.channels.base import BaseChannelAdapter, _time_ago, register
from memnex.memory.models import Memory


@register
class WhatsAppChannelAdapter(BaseChannelAdapter):
    channel = "whatsapp"

    def extract(self, raw: Any, metadata: dict | None = None) -> str:
        if isinstance(raw, str):
            return raw
        # Expected shape: list of {from, type, content, timestamp, media_url?}
        lines: list[str] = []
        for msg in raw or []:
            who = msg.get("from", "customer")
            typ = msg.get("type", "text")
            content = msg.get("content", "")
            if typ == "text":
                lines.append(f"{who}: {content}")
            elif typ in {"image", "document", "voice_note"}:
                ref = msg.get("media_url") or "<media>"
                lines.append(f"{who} shared {typ}: {ref} {content}".strip())
            elif typ == "location":
                lines.append(f"{who} shared location: {content}")
            else:
                lines.append(f"{who}: {content}")
        return "\n".join(lines)

    def format(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        header = self._header(memories)
        lines = [header]
        for m in memories[:8]:
            lines.append(f"- {m.fact_type.capitalize()}: {m.fact}")
        return "\n".join(lines)

    @staticmethod
    def _header(memories: list[Memory]) -> str:
        last = max(memories, key=lambda m: m.created_at)
        return (
            f"Previous interaction ({last.source_channel}, {_time_ago(last.created_at)}):"
        )
