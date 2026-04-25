"""Web chat channel adapter. Richer formatting — URLs allowed."""
from __future__ import annotations

from typing import Any

from memnex.channels.base import BaseChannelAdapter, _time_ago, register
from memnex.memory.models import Memory


@register
class WebChatChannelAdapter(BaseChannelAdapter):
    channel = "web"

    def extract(self, raw: Any, metadata: dict | None = None) -> str:
        if isinstance(raw, str):
            return raw
        # Expected: list of {from, content, page_url?, form_data?}
        lines: list[str] = []
        for event in raw or []:
            who = event.get("from", "customer")
            content = event.get("content", "")
            url = event.get("page_url")
            if url:
                lines.append(f"{who} on {url}: {content}")
            else:
                lines.append(f"{who}: {content}")
            form = event.get("form_data")
            if form:
                lines.append(f"(form submitted: {form})")
        return "\n".join(lines)

    def format(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        last = max(memories, key=lambda m: m.created_at)
        lines = [f"## Customer context (last seen {_time_ago(last.created_at)} via {last.source_channel})"]
        by_type: dict[str, list[Memory]] = {}
        for m in memories:
            by_type.setdefault(m.fact_type, []).append(m)
        for ftype in ("issue", "intent", "resolution", "profile", "preference", "event"):
            items = by_type.get(ftype, [])
            if not items:
                continue
            lines.append(f"\n**{ftype.capitalize()}**")
            for m in items[:5]:
                lines.append(f"- {m.fact}")
        return "\n".join(lines)
