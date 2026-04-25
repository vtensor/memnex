"""MCP Resources for Memnex.

Resources are read-only data the host application can fetch by URI. We
expose three:

- ``memnex://schema/fact-types`` — the 5-type taxonomy (static markdown).
- ``memnex://users/{user_id}/memories`` — what we remember about a user
  (live, tenant-scoped JSON).
- ``memnex://tenants/me/stats`` — per-tenant aggregate counts.

Each resource is tenant-scoped automatically because :class:`McpContext`
already carries ``(tenant_id, channel)`` resolved from the API key.
"""
from __future__ import annotations

import json
import re
from typing import Any

from memnex.mcp.tools import McpContext

# --- static content --------------------------------------------------------

_FACT_TYPES_MARKDOWN = """\
# Memnex fact-type taxonomy

Every fact written via `memory_write` has one of these five types. Pick the
type that matches what the user actually said or did. If multiple types fit,
write multiple facts.

## intent
Something the user wants to do. Future-tense or aspirational.

- "Wants to cancel order XYZ"
- "Plans to upgrade to the Pro plan next month"
- "Considering switching from Slack to Teams"

## preference
A soft preference about how things should be done. Stable across time.

- "Prefers morning calls (9-11 AM)"
- "Likes terse responses, no emojis"
- "Asks for vegetarian options at restaurants"

## profile
A stable user attribute — identity, location, role.

- "Name is Vikram Dev"
- "Based in Bangalore"
- "Works as a frontend engineer at Acme Corp"

## issue
An active problem the user reported. Open until resolved.

- "Order #4521 arrived damaged"
- "Cannot log in after password reset"
- "Charged twice for last month's subscription"

## resolution
How an issue was resolved or closed. Pair with the original issue.

- "Refund of ₹499 issued via UPI for order #4521"
- "Account access restored after manual unlock"
- "Duplicate charge reversed; credit posted"

## entities convention

The `entities` field on every fact is a list of normalized references the
fact is *about*. Format: `"type:value"`.

- Order IDs: `"order:4521"`
- Products: `"sku:SKU123"`
- Drugs: `"drug:penicillin"`
- Amounts: `"amount:499"`, `"currency:INR"`
- Appointments: `"appointment:apt_2026_05_01"`

Two facts that share an entity AND contradict each other will be detected
by the server's conflict resolver. Always include the relevant identifiers
so the conflict path can fire.

## When to write

Write the moment a fact crystallizes — not at end-of-conversation. A
20-turn call typically produces 3-5 writes, not 1 or 20. Mid-session
disconnects are common; only written facts survive.

Do NOT write greetings, acknowledgements, filler, or repeats of facts
already on file.
"""


# --- URI router ------------------------------------------------------------

_USER_MEMORIES_RE = re.compile(r"^memnex://users/(?P<user_id>[^/]+)/memories$")


class ResourceError(ValueError):
    """Raised when a URI cannot be served — surfaces as a clean error."""


class ResourceRouter:
    """Resolves a URI to its serialized payload.

    Tenant scoping is implicit: the underlying ``Memnex`` client is already
    scoped to one tenant (from the API key). Cross-tenant URIs are
    impossible by construction.
    """

    def __init__(self, ctx: McpContext) -> None:
        self._ctx = ctx

    async def read(self, uri: str) -> tuple[str, str]:
        """Return ``(content, mime_type)``."""
        if uri == "memnex://schema/fact-types":
            return _FACT_TYPES_MARKDOWN, "text/markdown"

        if uri == "memnex://tenants/me/stats":
            stats = await self._ctx.mx.stats()
            return json.dumps(stats, default=str, indent=2), "application/json"

        m = _USER_MEMORIES_RE.match(uri)
        if m:
            user_id = m.group("user_id")
            payload = await self._user_memories(user_id)
            return json.dumps(payload, default=str, indent=2), "application/json"

        raise ResourceError(f"unknown resource URI: {uri}")

    async def _user_memories(self, user_id: str) -> dict[str, Any]:
        memories = await self._ctx.mx.user_read(
            user_id=user_id,
            channel=self._ctx.channel,
            as_text=False,
        )
        return {
            "user_id": user_id,
            "channel": self._ctx.channel,
            "count": len(memories),
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "fact": m.fact,
                    "fact_type": m.fact_type,
                    "entities": m.entities,
                    "salience": m.salience,
                    "source_channel": m.source_channel,
                    "created_at": m.created_at,
                    "updated_at": m.updated_at,
                }
                for m in memories
            ],
        }


# --- registry exposed to server.py ----------------------------------------

def static_resources() -> list[dict[str, str]]:
    """Resources with concrete URIs (not templates). Returned to MCP clients
    as ``Resource`` objects."""
    return [
        {
            "uri": "memnex://schema/fact-types",
            "name": "fact-types",
            "title": "Memnex fact-type taxonomy",
            "description": (
                "The 5 fact types (intent, preference, profile, issue, "
                "resolution) with examples and the entities convention. "
                "Read this once at agent startup to learn how to populate "
                "memory_write."
            ),
            "mimeType": "text/markdown",
        },
        {
            "uri": "memnex://tenants/me/stats",
            "name": "tenant-stats",
            "title": "Tenant memory statistics",
            "description": (
                "Aggregate counts for the current tenant — total memories, "
                "by-type breakdown, oldest/newest timestamps. Suitable for "
                "an admin dashboard or health check."
            ),
            "mimeType": "application/json",
        },
    ]


def resource_templates() -> list[dict[str, str]]:
    """URI templates (RFC 6570 style) for parameterized resources."""
    return [
        {
            "uriTemplate": "memnex://users/{user_id}/memories",
            "name": "user-memories",
            "title": "Memories for one user",
            "description": (
                "All active memories Memnex holds for the given user_id. "
                "Tenant-scoped automatically. Use this to render a "
                "'what we remember' panel in your support UI."
            ),
            "mimeType": "application/json",
        },
    ]
