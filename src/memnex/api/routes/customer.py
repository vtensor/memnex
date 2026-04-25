"""/customer/* routes — per-customer admin and GDPR."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from memnex.api.middleware.auth import require_api_key
from memnex.api.middleware.rate_limit import rate_limit

router = APIRouter(prefix="/customer", tags=["customer"])


@router.delete("/{customer_id}")
async def forget(
    customer_id: str,
    request: Request,
    reason: str = "gdpr_request",
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> dict:
    mx = request.app.state.memnex
    return await mx.forget_customer(customer_id=customer_id, reason=reason)


@router.get("/{customer_id}/export")
async def export(
    customer_id: str,
    request: Request,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> dict:
    mx = request.app.state.memnex
    return await mx.export_customer_data(customer_id=customer_id, format="json")


@router.get("/{customer_id}/timeline")
async def timeline(
    customer_id: str,
    request: Request,
    limit: int = 50,
    _tenant: str = Depends(require_api_key),
    _rate: None = Depends(rate_limit),
) -> dict:
    mx = request.app.state.memnex
    memories = await mx.get_timeline(customer_id=customer_id, limit=limit)
    return {"items": [m.model_dump(mode="json") for m in memories]}
