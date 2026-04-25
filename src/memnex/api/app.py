"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

from memnex.client import Memnex
from memnex.config import MemnexConfig


def mount_rest(app: "FastAPI", mx: Memnex) -> None:
    """Attach /api/v1/* routes to an existing FastAPI app."""
    from memnex.api.routes import admin, customer, identity, memory

    app.state.memnex = mx
    app.include_router(memory.router, prefix="/api/v1")
    app.include_router(identity.router, prefix="/api/v1")
    app.include_router(customer.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")


def build_app(config: MemnexConfig) -> "FastAPI":
    try:
        from fastapi import FastAPI
    except ImportError as e:
        raise ImportError("`pip install memnex[api]`.") from e

    @asynccontextmanager
    async def lifespan(app: "FastAPI"):
        mx = await Memnex.create(config=config)
        app.state.memnex = mx
        try:
            yield
        finally:
            await mx.close()

    app = FastAPI(
        title="Memnex API",
        description="Cross-channel memory infrastructure.",
        version="0.1.0",
        lifespan=lifespan,
    )

    from memnex.api.routes import admin, customer, identity, memory

    app.include_router(memory.router, prefix="/api/v1")
    app.include_router(identity.router, prefix="/api/v1")
    app.include_router(customer.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    return app
