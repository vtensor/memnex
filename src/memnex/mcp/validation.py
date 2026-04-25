"""MCP boundary validation.

Every MCP tool invocation goes through these validators before anything
downstream touches storage or the LLM. They enforce:

- Hard size caps (DoS prevention).
- Shape checks (no control chars in ``user_id``; list-of-strings for
  ``facts``; known enum for ``target_format``).

Validators raise :class:`ValidationError`. The MCP server converts that
into a structured tool response (``{"error": "bad_request", ...}``) so
the caller gets a clean signal rather than a 500 / crash.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

# Size caps — values chosen to be generous for real use, strict enough
# to block obvious DoS / memory-bomb payloads.
MAX_USER_ID_LEN = 256
MAX_FACTS_ITEMS = 50
MAX_FACT_CHARS = 4096
MAX_RAW_TEXT_BYTES = 50_000
MAX_QUERY_LEN = 2048
MAX_SESSION_ID_LEN = 256
MAX_SOURCE_LEN = 128

_VALID_TARGET_FORMATS = {"voice", "whatsapp", "web", "sms", "app"}
_VALID_TRUST_LEVELS = {
    "user_content", "agent_action", "verified_external", "system",
}


class ValidationError(ValueError):
    """Raised on MCP input validation failure. Serialised as bad_request."""


# Agent-facing fact schema. Keep this tight — 4 fields, 5 types. Any extra
# metadata the server needs (salience, channel, timestamps) is derived, not
# accepted from the agent.
AgentFactType = Literal["intent", "preference", "issue", "resolution", "profile"]


class FactInput(BaseModel):
    """Structured fact the agent submits via memory_write."""

    fact: str = Field(
        min_length=1,
        max_length=MAX_FACT_CHARS,
        description=(
            "A single concise statement about the user, in natural language. "
            "Examples: 'Wants to cancel order XYZ', 'Prefers morning calls', "
            "'Reported that item arrived damaged'. One fact per entry — do "
            "not pack multiple facts into one string."
        ),
    )
    type: AgentFactType = Field(
        description=(
            "What kind of fact this is:\n"
            "- 'intent': user wants to do something ('wants to cancel', 'plans to upgrade')\n"
            "- 'preference': soft preference ('prefers email over SMS', 'likes spicy food')\n"
            "- 'profile': stable user attribute ('name is Vikram', 'based in Bangalore')\n"
            "- 'issue': an active problem the user reported ('order arrived damaged')\n"
            "- 'resolution': how an issue was resolved ('refund issued via UPI')"
        ),
    )
    entities: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Normalized references the fact is ABOUT — used for conflict "
            "detection and entity-scoped retrieval. Format: 'type:value'. "
            "Examples: ['order:XYZ'], ['sku:SKU123', 'amount:499'], "
            "['drug:penicillin', 'severity:severe']. Leave empty if the "
            "fact has no specific identifiers (e.g. a general preference)."
        ),
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description=(
            "How certain the agent is about this fact, 0.0-1.0. Use 0.9+ "
            "when the user stated it explicitly; lower (0.5-0.8) when "
            "inferred from context."
        ),
    )

    # Reject unknown fields so typos surface instead of being silently dropped.
    model_config = {"extra": "forbid"}


def validate_user_id(v: Any) -> str:
    if not isinstance(v, str):
        raise ValidationError("user_id must be a string")
    if not v:
        raise ValidationError("user_id must be non-empty")
    if len(v) > MAX_USER_ID_LEN:
        raise ValidationError(
            f"user_id exceeds {MAX_USER_ID_LEN} chars"
        )
    # No control chars / newlines — keeps storage keys + log lines clean.
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise ValidationError("user_id contains control characters")
    return v


def validate_facts(v: Any) -> list[str | FactInput]:
    """Accept either plain strings (legacy) or structured fact dicts.

    Plain strings get classified downstream by the rule-based extractor.
    Structured dicts are validated via ``FactInput`` and bypass classification
    entirely — no LLM on the hot path.
    """
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValidationError("facts must be a list")
    if len(v) > MAX_FACTS_ITEMS:
        raise ValidationError(
            f"facts exceeds {MAX_FACTS_ITEMS} items"
        )
    out: list[str | FactInput] = []
    for i, item in enumerate(v):
        if isinstance(item, str):
            if len(item) > MAX_FACT_CHARS:
                raise ValidationError(
                    f"facts[{i}] exceeds {MAX_FACT_CHARS} chars"
                )
            out.append(item)
            continue
        if isinstance(item, dict):
            try:
                out.append(FactInput(**item))
            except PydanticValidationError as e:
                # Surface the first error path for a clean agent message.
                first = e.errors()[0]
                loc = ".".join(str(p) for p in first["loc"])
                raise ValidationError(
                    f"facts[{i}].{loc}: {first['msg']}"
                ) from None
            continue
        raise ValidationError(
            f"facts[{i}] must be a string or an object with "
            f"{{fact, type, entities, confidence}}"
        )
    return out


def validate_raw_text(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValidationError("raw_text must be a string")
    if len(v.encode("utf-8")) > MAX_RAW_TEXT_BYTES:
        raise ValidationError(
            f"raw_text exceeds {MAX_RAW_TEXT_BYTES} bytes"
        )
    return v


def validate_query(v: Any) -> str:
    if not isinstance(v, str):
        raise ValidationError("query must be a string")
    if not v.strip():
        raise ValidationError("query must be non-empty")
    if len(v) > MAX_QUERY_LEN:
        raise ValidationError(f"query exceeds {MAX_QUERY_LEN} chars")
    return v


def validate_target_format(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or v not in _VALID_TARGET_FORMATS:
        raise ValidationError(
            f"target_format must be one of: {sorted(_VALID_TARGET_FORMATS)}"
        )
    return v


def validate_trust_level(v: Any) -> str:
    if not isinstance(v, str) or v not in _VALID_TRUST_LEVELS:
        raise ValidationError(
            f"trust_level must be one of: {sorted(_VALID_TRUST_LEVELS)}"
        )
    return v


def validate_session_id(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValidationError("session_id must be a string")
    if len(v) > MAX_SESSION_ID_LEN:
        raise ValidationError(
            f"session_id exceeds {MAX_SESSION_ID_LEN} chars"
        )
    return v


def validate_source(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValidationError("source must be a string")
    if len(v) > MAX_SOURCE_LEN:
        raise ValidationError(f"source exceeds {MAX_SOURCE_LEN} chars")
    return v


def validate_positive_int(v: Any, *, name: str, default: int, max_value: int) -> int:
    if v is None:
        return default
    if not isinstance(v, int) or isinstance(v, bool):
        raise ValidationError(f"{name} must be an int")
    if v < 1:
        raise ValidationError(f"{name} must be >= 1")
    if v > max_value:
        raise ValidationError(f"{name} exceeds {max_value}")
    return v
