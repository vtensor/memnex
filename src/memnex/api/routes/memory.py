"""/memory/* routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from memnex.api.middleware.auth import require_api_key
from memnex.api.middleware.rate_limit import rate_limit
from memnex.api.models import (
    ReadRequest,
    ReadResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    WriteRequest,
    WriteResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/write", response_model=WriteResponse)
async def write(
    body: WriteRequest,
    request: Request,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> WriteResponse:
    mx = request.app.state.memnex
    memories = await mx.write(
        channel=body.channel,
        identifier=body.identifier,
        facts=body.facts,
        raw_text=body.raw_text,
        session_id=body.session_id,
        source_agent_id=body.source_agent_id,
        ttl_hours=body.ttl_hours,
        metadata=body.metadata,
    )
    return WriteResponse(written=len(memories), memory_ids=[m.memory_id for m in memories])


@router.get("/read", response_model=ReadResponse)
async def read(
    channel: str,
    identifier: str,
    request: Request,
    target_channel: str | None = None,
    token_budget: int = 2000,
    fact_type: str | None = None,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> ReadResponse:
    mx = request.app.state.memnex
    ctx = await mx.read(
        channel=channel,
        identifier=identifier,
        target_channel=target_channel,
        token_budget=token_budget,
        fact_type=fact_type,
    )
    return ReadResponse(context=ctx)


@router.post("/read", response_model=ReadResponse)
async def read_post(
    body: ReadRequest,
    request: Request,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> ReadResponse:
    mx = request.app.state.memnex
    ctx = await mx.read(
        channel=body.channel,
        identifier=body.identifier,
        target_channel=body.target_channel,
        token_budget=body.token_budget,
        fact_type=body.fact_type,
    )
    return ReadResponse(context=ctx)


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    request: Request,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> SearchResponse:
    mx = request.app.state.memnex
    results = await mx.search(
        channel=body.channel,
        identifier=body.identifier,
        query=body.query,
        max_results=body.max_results,
    )
    return SearchResponse(
        results=[
            SearchResultItem(
                memory_id=m.memory_id,
                fact=m.fact,
                type=m.fact_type,
                salience=m.salience,
                channel=m.source_channel,
            )
            for m in results
        ]
    )
