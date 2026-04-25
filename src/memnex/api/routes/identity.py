"""/identity/* routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from memnex.api.middleware.auth import require_api_key
from memnex.api.middleware.rate_limit import rate_limit
from memnex.api.models import LinkRequest, LinkResponse, ResolveRequest, ResolveResponse

router = APIRouter(prefix="/identity", tags=["identity"])


@router.post("/resolve", response_model=ResolveResponse)
async def resolve(
    body: ResolveRequest,
    request: Request,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> ResolveResponse:
    mx = request.app.state.memnex
    customer = await mx.resolve(
        channel=body.channel,
        identifier=body.identifier,
        hint_name=body.hint_name,
        hint_topic=body.hint_topic,
        auto_create=body.auto_create,
    )
    return ResolveResponse(
        id=customer.id,
        channels=[c for c in customer.channels],
        last_channel=customer.last_channel,
        identifiers=[i.model_dump(mode="json") for i in customer.identifiers],
        metadata=customer.metadata,
    )


@router.post("/link", response_model=LinkResponse)
async def link(
    body: LinkRequest,
    request: Request,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> LinkResponse:
    mx = request.app.state.memnex
    if body.customer_id:
        customer_id = body.customer_id
    elif body.channel_a and body.identifier_a:
        customer = await mx.resolve(body.channel_a, body.identifier_a)
        customer_id = customer.id
    else:
        raise HTTPException(
            status_code=400,
            detail="pass customer_id or (channel_a, identifier_a)",
        )
    ident = await mx.link_identity(
        customer_id=customer_id,
        channel=body.channel_b,
        identifier=body.identifier_b,
        linked_by=body.linked_by,
    )
    return LinkResponse(customer_id=customer_id, identifier_id=ident.identifier_id)
