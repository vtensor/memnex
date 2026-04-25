"""Pydantic request / response models for the REST API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WriteRequest(BaseModel):
    channel: str
    identifier: str
    facts: list[str] | None = None
    raw_text: str | None = None
    session_id: str | None = None
    source_agent_id: str | None = None
    ttl_hours: int | None = None
    metadata: dict[str, Any] | None = None


class WriteResponse(BaseModel):
    written: int
    memory_ids: list[str]


class ReadRequest(BaseModel):
    channel: str
    identifier: str
    target_channel: str | None = None
    token_budget: int = 2000
    fact_type: str | None = None


class ReadResponse(BaseModel):
    context: str


class SearchRequest(BaseModel):
    channel: str
    identifier: str
    query: str
    max_results: int = 5


class SearchResultItem(BaseModel):
    memory_id: str
    fact: str
    type: str
    salience: float
    channel: str


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


class LinkRequest(BaseModel):
    customer_id: str | None = None
    channel_a: str | None = None
    identifier_a: str | None = None
    channel_b: str
    identifier_b: str
    linked_by: str = "manual"


class LinkResponse(BaseModel):
    customer_id: str
    identifier_id: str


class ResolveRequest(BaseModel):
    channel: str
    identifier: str
    hint_name: str | None = None
    hint_topic: str | None = None
    auto_create: bool = True


class ResolveResponse(BaseModel):
    id: str
    channels: list[str]
    last_channel: str | None
    identifiers: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
