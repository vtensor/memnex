"""/health, /metrics, /stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from memnex.api.middleware.auth import require_api_key

router = APIRouter(tags=["admin"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    try:
        from prometheus_client import generate_latest
        return generate_latest().decode()
    except ImportError:
        return "# prometheus_client not installed\n"


@router.get("/stats")
async def stats(
    request: Request,
    _tenant: str = Depends(require_api_key),
) -> dict:
    mx = request.app.state.memnex
    return await mx.stats()
