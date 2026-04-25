"""Identity domain models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Channel = Literal["voice", "whatsapp", "web", "app", "sms", "email"]
IdentifierType = Literal[
    "phone", "email", "session_cookie", "app_user_id", "whatsapp_id", "sms_number"
]
LinkedBy = Literal["system", "agent", "manual", "otp_verification"]


class ChannelIdentifier(BaseModel):
    identifier_id: str
    customer_id: str
    channel: Channel
    identifier: str
    identifier_type: IdentifierType
    confidence: float = 1.0
    linked_by: LinkedBy = "system"
    created_at: datetime


class Customer(BaseModel):
    id: str
    tenant_id: str
    created_at: datetime
    last_seen_at: datetime | None = None
    last_channel: Channel | None = None
    channels: list[Channel] = Field(default_factory=list)
    identifiers: list[ChannelIdentifier] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Match(BaseModel):
    """Result of checking whether two identifiers belong to the same customer."""

    is_same: bool
    confidence: float
    customer_id: str | None = None
    linked_by: LinkedBy | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class CandidateLink(BaseModel):
    link_id: str
    customer_id_a: str
    customer_id_b: str
    confidence: float
    evidence: dict[str, Any]
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    created_at: datetime
