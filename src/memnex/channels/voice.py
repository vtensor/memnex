"""Voice channel adapter."""
from __future__ import annotations

import re
from typing import Any

from memnex.channels.base import BaseChannelAdapter, _time_ago, register
from memnex.memory.models import Memory

_FILLER = re.compile(
    r"\b(um+|uh+|er+|ah+|like|you know|i mean|sort of|kind of)\b",
    re.IGNORECASE,
)
_REPEAT = re.compile(
    r"(\b\w+(?:\s+\w+){0,3}\b)(?:[,\s]+\1\b)+",
    re.IGNORECASE,
)  # "my order, my order" / "the the"
_PAUSE = re.compile(r"\s{2,}|\.{3,}")


@register
class VoiceChannelAdapter(BaseChannelAdapter):
    channel = "voice"

    def extract(self, raw: Any, metadata: dict | None = None) -> str:
        text = raw if isinstance(raw, str) else str(raw)
        text = _FILLER.sub("", text)
        text = _REPEAT.sub(r"\1", text)
        text = _PAUSE.sub(" ", text)
        return text.strip()

    def format(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        # Voice: natural-language summary. No URLs. Max ~75 words.
        most_recent = max(memories, key=lambda m: m.created_at)
        when = _time_ago(most_recent.created_at)

        issues = [m for m in memories if m.fact_type == "issue"]
        intents = [m for m in memories if m.fact_type == "intent"]
        profile = [m for m in memories if m.fact_type == "profile"]

        parts: list[str] = [f"This customer last interacted {when} on {most_recent.source_channel}."]
        if issues:
            parts.append(_strip_urls(issues[0].fact).rstrip("."))
        if intents:
            parts.append("They're asking for " + _strip_urls(intents[0].fact).rstrip(".").lower() + ".")
        if profile:
            parts.append(_strip_urls(profile[0].fact).rstrip("."))

        summary = " ".join(parts)
        # Cap ~75 words.
        words = summary.split()
        if len(words) > 75:
            summary = " ".join(words[:75]) + "..."
        return summary


_URL = re.compile(r"https?://\S+")


def _strip_urls(text: str) -> str:
    return _URL.sub("", text).strip()
