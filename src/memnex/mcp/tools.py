"""MCP tool handlers.

**Contract.** Every tool takes a ``user_id`` — an opaque string the tenant
chooses. Memnex does not interpret it; we only scope memory to
``(tenant_id, user_id)``. The tenant is identified server-side from the
``MEMNEX_SECRET_KEY`` API key that started the MCP process, so neither the
agent nor its LLM needs to know or pass the tenant id.

MCP client env:
    MEMNEX_SECRET_KEY   # "mx_live_kXXXX_..."  -> identifies tenant
    MEMNEX_CHANNEL      # optional metadata, e.g. "voice"
    MEMNEX_LLM_PROVIDER # optional, for LLM-based extraction

Everything else (Postgres / Redis / Qdrant / audit key / JWT key) lives in
the server process environment only.
"""
from __future__ import annotations

from typing import Any

from memnex.client import Memnex
from memnex.mcp import validation as v
from memnex.mcp.validation import FactInput, ValidationError
from memnex.memory.models import Fact
from memnex.provenance.filter import InjectionFilter

# Module-level singleton: the filter is stateless + cheap to construct.
_INJECTION_FILTER = InjectionFilter()


class McpContext:
    """What the MCP server knows about the current connection.

    - ``mx``: Memnex client scoped to this tenant.
    - ``tenant_id``: resolved from the API key at server startup.
    - ``channel``: static label from ``MEMNEX_CHANNEL``.
    """

    def __init__(self, mx: Memnex, tenant_id: str, channel: str) -> None:
        self.mx = mx
        self.tenant_id = tenant_id
        self.channel = channel


def _assert_no_injection(payloads: list[str | None]) -> None:
    """MCP-level injection floor. Runs on every write.

    Tenants can further tighten via ``TrustPolicy`` but they cannot turn
    this off — the SaaS product enforces it regardless of per-tenant
    policy. Raises ``ValidationError`` on any hit so the caller sees
    a structured ``bad_request`` rather than silent failure.
    """
    for payload in payloads:
        if not payload:
            continue
        hits = _INJECTION_FILTER.scan(payload)
        if hits:
            raise ValidationError(
                f"injection pattern detected: {hits[0].pattern}"
            )


def build_tool_handlers(ctx: McpContext) -> dict[str, Any]:
    async def memory_write(
        user_id: str | None = None,
        facts: list[str] | None = None,
        raw_text: str | None = None,
        session_id: str | None = None,
        trust_level: str = "user_content",
        source: str | None = None,
    ) -> dict:
        uid = v.validate_user_id(user_id)
        facts_v = v.validate_facts(facts)
        raw_v = v.validate_raw_text(raw_text)
        session_v = v.validate_session_id(session_id)
        trust_v = v.validate_trust_level(trust_level)
        source_v = v.validate_source(source)
        if not facts_v and not raw_v:
            raise ValidationError("pass either facts or raw_text")

        # Injection floor runs on string payloads. Structured FactInputs still
        # get scanned on their `fact` text.
        _assert_no_injection(
            [raw_v, *[f if isinstance(f, str) else f.fact for f in facts_v]]
        )

        # Structured dicts -> Fact objects (bypass rule-based classification);
        # plain strings flow through the extractor as before.
        mixed: list[str | Fact] = [
            Fact(
                fact=f.fact, type=f.type, entities=f.entities, confidence=f.confidence
            )
            if isinstance(f, FactInput)
            else f
            for f in facts_v
        ]

        memories = await ctx.mx.user_write(
            user_id=uid,
            channel=ctx.channel,
            facts=mixed or None,
            raw_text=raw_v,
            session_id=session_v,
            trust_level=trust_v,
            source=source_v,
        )
        return {
            "written": len(memories),
            "memory_ids": [m.memory_id for m in memories],
        }

    async def memory_read(
        user_id: str | None = None,
        token_budget: int | None = None,
        target_format: str | None = None,
    ) -> dict:
        uid = v.validate_user_id(user_id)
        budget = v.validate_positive_int(
            token_budget, name="token_budget", default=2000, max_value=32_000,
        )
        fmt = v.validate_target_format(target_format)

        ctx_text = await ctx.mx.user_read(
            user_id=uid,
            channel=ctx.channel,
            target_format=fmt,
            token_budget=budget,
        )
        return {"context": ctx_text}

    async def memory_search(
        user_id: str | None = None,
        query: str | None = None,
        max_results: int | None = None,
    ) -> dict:
        uid = v.validate_user_id(user_id)
        q = v.validate_query(query)
        limit = v.validate_positive_int(
            max_results, name="max_results", default=5, max_value=50,
        )

        results = await ctx.mx.user_search(
            user_id=uid, query=q, max_results=limit,
        )
        return {
            "results": [
                {
                    "memory_id": m.memory_id,
                    "fact": m.fact,
                    "type": m.fact_type,
                    "salience": m.salience,
                }
                for m in results
            ]
        }

    async def memory_forget(
        user_id: str | None = None,
        reason: str = "gdpr_request",
    ) -> dict:
        uid = v.validate_user_id(user_id)
        if not isinstance(reason, str) or len(reason) > 256:
            raise ValidationError("reason must be a string <= 256 chars")
        return await ctx.mx.user_forget(user_id=uid, reason=reason)

    async def memory_trace(
        user_id: str | None = None,
        agent_output: str | None = None,
    ) -> dict:
        """Trace agent output back to source memories. Empty = hallucination."""
        uid = v.validate_user_id(user_id)
        if not isinstance(agent_output, str) or not agent_output.strip():
            raise ValidationError("agent_output must be a non-empty string")
        if len(agent_output) > 50_000:
            raise ValidationError("agent_output exceeds 50000 chars")

        hits = await ctx.mx.user_trace(
            user_id=uid, agent_output=agent_output,
        )
        return {"hits": hits}

    return {
        "memory_write": memory_write,
        "memory_read": memory_read,
        "memory_search": memory_search,
        "memory_forget": memory_forget,
        "memory_trace": memory_trace,
    }


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "memory_write",
        "description": (
            "Store durable facts about the end user into permanent cross-channel "
            "memory. Call this the MOMENT a fact crystallizes in the conversation: "
            "a declared intent ('wants to cancel X'), a preference ('prefers "
            "mornings'), an issue raised ('item damaged'), a resolution reached "
            "('refund processed'), or a profile attribute ('name is Vikram'). "
            "Do NOT call this for greetings, acknowledgements, filler, or turns "
            "that restate something already written. Write as facts appear, "
            "not as one batch at the end of the conversation — mid-session "
            "disconnects are common and only written facts survive. "
            "`user_id` is the tenant's opaque identifier for the end user."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Opaque tenant-chosen identifier for the end user.",
                },
                "facts": {
                    "type": "array",
                    "description": (
                        "One or more structured facts to persist. Prefer this over "
                        "`raw_text`. Each fact is a self-contained object — do not "
                        "pack multiple facts into one entry."
                    ),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["fact", "type"],
                        "properties": {
                            "fact": {
                                "type": "string",
                                "maxLength": 4096,
                                "description": (
                                    "A concise natural-language statement. "
                                    "Examples: 'Wants to cancel order XYZ', "
                                    "'Prefers morning calls'."
                                ),
                            },
                            "type": {
                                "type": "string",
                                "enum": [
                                    "intent", "preference", "issue",
                                    "resolution", "profile",
                                ],
                                "description": (
                                    "intent = user wants to do something; "
                                    "preference = soft preference; "
                                    "profile = stable user attribute; "
                                    "issue = active problem reported; "
                                    "resolution = how an issue was resolved."
                                ),
                            },
                            "entities": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 50,
                                "default": [],
                                "description": (
                                    "Normalized references the fact is about, "
                                    "formatted 'type:value'. Examples: "
                                    "['order:XYZ'], ['sku:SKU123','amount:499']. "
                                    "Used for conflict detection — two facts that "
                                    "share an entity and contradict each other "
                                    "will be merged/superseded by the server. "
                                    "Leave empty for general preferences."
                                ),
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                                "default": 0.9,
                                "description": (
                                    "0.0-1.0. Use 0.9+ when the user stated it "
                                    "explicitly, lower when inferred."
                                ),
                            },
                        },
                    },
                },
                "raw_text": {
                    "type": "string",
                    "description": (
                        "LEGACY. Unstructured turn text; the server will attempt "
                        "to extract facts from it. Prefer `facts` for cost, "
                        "latency, and accuracy. Provide either `facts` or "
                        "`raw_text`, not both."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional opaque session label. Metadata only.",
                },
                "trust_level": {
                    "type": "string",
                    "enum": [
                        "user_content", "agent_action",
                        "verified_external", "system",
                    ],
                    "default": "user_content",
                },
                "source": {
                    "type": "string",
                    "description": "Optional source label (e.g. 'voice_call_2025_04_25').",
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "memory_read",
        "description": (
            "Fetch formatted memory context for this user. Returns a string "
            "sized to ``token_budget``."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "token_budget": {"type": "integer", "default": 2000},
                "target_format": {
                    "type": "string",
                    "enum": ["voice", "whatsapp", "web", "sms", "app"],
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "memory_search",
        "description": "Semantic search over this user's memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["user_id", "query"],
        },
    },
    {
        "name": "memory_forget",
        "description": "Purge all memories for this user (GDPR erasure).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "reason": {"type": "string", "default": "gdpr_request"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "memory_trace",
        "description": (
            "Given a piece of agent output, return the list of stored "
            "memories that could have produced it. Empty = suspected "
            "hallucination."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "agent_output": {"type": "string"},
            },
            "required": ["user_id", "agent_output"],
        },
    },
]
