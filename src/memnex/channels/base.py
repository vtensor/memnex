"""Channel adapter protocol.

Adapters do two things:

1. ``extract``: turn raw channel-specific content (voice transcript, WhatsApp
   messages, web clicks) into a normalized text string ready for the
   extractor. This is where we strip voice filler words or inline WhatsApp
   media references.
2. ``format``: render a list of Memory objects for the target channel. A
   voice agent wants short spoken summaries; a WhatsApp agent wants bullet
   facts with media refs. Same memories, different presentation.
"""
from __future__ import annotations

from memnex._time import utcnow

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from memnex.memory.models import Memory


def _time_ago(when: datetime | None) -> str:
    if not when:
        return "earlier"
    delta = utcnow() - when
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() / 60)} min ago"
    if hours < 24:
        return f"{int(hours)}h ago"
    return f"{int(hours / 24)}d ago"


class BaseChannelAdapter(ABC):
    channel: str

    @abstractmethod
    def extract(self, raw: Any, metadata: dict | None = None) -> str:
        """Turn raw channel content into a cleaned-up text string."""

    @abstractmethod
    def format(self, memories: list[Memory]) -> str:
        """Format memories for an agent on this channel."""


_ADAPTERS: dict[str, type[BaseChannelAdapter]] = {}


def register(cls: type[BaseChannelAdapter]) -> type[BaseChannelAdapter]:
    _ADAPTERS[cls.channel] = cls
    return cls


def get_adapter(channel: str) -> BaseChannelAdapter:
    # Lazy-load to avoid circular imports during package init.
    if not _ADAPTERS:
        from memnex.channels import app, sms, voice, web, whatsapp  # noqa: F401
    cls = _ADAPTERS.get(channel)
    if cls is None:
        raise ValueError(f"No adapter registered for channel: {channel}")
    return cls()


__all__ = ["BaseChannelAdapter", "get_adapter", "register", "_time_ago"]
