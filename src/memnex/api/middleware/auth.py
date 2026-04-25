"""API key auth middleware.

Single mandatory header: ``X-Memnex-API-Key``. Key -> tenant_id mapping is
loaded from ``MEMNEX_API_KEYS`` env var as ``key1:tenant1,key2:tenant2``.
Leave unset in dev to disable auth (logs a warning).

This layer is deliberately thin — production deployments should front the
API with a proper gateway (Kong, APISIX, AWS API Gateway).
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request


def _load_keys() -> dict[str, str]:
    raw = os.getenv("MEMNEX_API_KEYS", "")
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        k, _, v = pair.partition(":")
        if k and v:
            out[k] = v
    return out


_KEYS = _load_keys()


async def require_api_key(request: Request) -> str:
    """FastAPI dependency — returns the tenant_id for this request."""
    if not _KEYS:
        # Dev mode: accept anything, use configured tenant.
        return request.app.state.memnex.config.tenant_id

    supplied = request.headers.get("X-Memnex-API-Key")
    if not supplied or supplied not in _KEYS:
        raise HTTPException(status_code=401, detail="invalid or missing api key")

    tenant = _KEYS[supplied]
    configured = request.app.state.memnex.config.tenant_id
    if tenant != configured:
        raise HTTPException(status_code=403, detail="api key not allowed for this tenant")
    return tenant
