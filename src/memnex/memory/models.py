"""Memory domain models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FactType = Literal["event", "intent", "profile", "preference", "issue", "resolution"]


class Fact(BaseModel):
    """An extracted fact, before it is persisted as a Memory."""

    fact: str
    type: FactType = "event"
    entities: list[str] = Field(default_factory=list)
    confidence: float = 0.9


class Memory(BaseModel):
    """A persisted memory — a fact with storage metadata."""

    memory_id: str
    tenant_id: str
    customer_id: str

    fact: str
    fact_type: FactType
    entities: list[str] = Field(default_factory=list)

    salience: float = 0.5
    source_channel: str
    source_agent_id: str | None = None
    session_id: str | None = None

    superseded_by: str | None = None
    is_active: bool = True

    embedding_id: str | None = None

    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    contains_pii: bool = False
    pii_fields: list[str] = Field(default_factory=list)
    consent_basis: str = "legitimate_interest"

    metadata: dict[str, Any] = Field(default_factory=dict)


class Conflict(BaseModel):
    existing: Memory
    incoming: Fact
    similarity: float
    resolution: Literal["supersede", "keep_both", "defer"] = "supersede"
