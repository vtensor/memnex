"""In-app adapter. Returns JSON-shaped context so the app UI can render it."""
from __future__ import annotations

import json
from typing import Any

from memnex.channels.base import BaseChannelAdapter, register
from memnex.memory.models import Memory


@register
class InAppChannelAdapter(BaseChannelAdapter):
    channel = "app"

    def extract(self, raw: Any, metadata: dict | None = None) -> str:
        if isinstance(raw, str):
            return raw
        return json.dumps(raw, default=str)

    def format(self, memories: list[Memory]) -> str:
        payload = {
            "memories": [
                {
                    "id": m.memory_id,
                    "fact": m.fact,
                    "type": m.fact_type,
                    "salience": m.salience,
                    "channel": m.source_channel,
                    "created_at": m.created_at.isoformat(),
                    "entities": m.entities,
                }
                for m in memories
            ]
        }
        return json.dumps(payload, indent=2)
