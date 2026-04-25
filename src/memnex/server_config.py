"""Server-side config — infrastructure that only the SaaS operator sees.

Loaded from OS env at boot. Never exposed to tenants, never logged, never
returned from any API. Tenant-facing secrets (``tenant.MEMNEX_SECRET_KEY``)
are separate — see ``memnex.saas.keys``.
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class ServerInfra(BaseModel):
    """Storage + signing infrastructure the service operator provides."""

    postgres_url: str | None = None
    redis_url: str | None = None
    qdrant_url: str | None = None

    # HMAC key that signs audit receipts so tenants can prove (to us or to a
    # regulator) that their audit trail hasn't been tampered with.
    audit_key: str | None = None

    # JWT signing key for dashboard session tokens (register/login flow).
    # We issue + verify these. Not tenant-facing.
    jwt_signing_key: str | None = None

    model_config = {"frozen": True}


@lru_cache(maxsize=1)
def server_infra() -> ServerInfra:
    return ServerInfra(
        postgres_url=os.getenv("MEMNEX_POSTGRES_URL"),
        redis_url=os.getenv("MEMNEX_REDIS_URL"),
        qdrant_url=os.getenv("MEMNEX_QDRANT_URL"),
        audit_key=os.getenv("MEMNEX_AUDIT_KEY"),
        jwt_signing_key=os.getenv("MEMNEX_JWT_SIGNING_KEY"),
    )
