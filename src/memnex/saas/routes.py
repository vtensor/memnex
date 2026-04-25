"""FastAPI routes for the tenant dashboard.

Surfaces:

- ``POST /auth/register`` — create a tenant account.
- ``POST /auth/login`` — email/password -> JWT session.
- ``POST /api-keys`` — JWT required. Mint a new API key for MCP.
- ``GET  /api-keys`` — JWT required. List keys (public metadata only).
- ``DELETE /api-keys/{key_id}`` — JWT required. Revoke a key.

Mounted under ``/api/v1/saas/`` by :func:`mount_saas`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from memnex.saas.accounts import (
    AuthError,
    TenantStore,
    issue_session_jwt,
    verify_session_jwt,
)
from memnex.server_config import server_infra

router = APIRouter(prefix="/saas", tags=["saas"])


# --- request/response models ---------------------------------------------
class RegisterReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class TokenResp(BaseModel):
    session_jwt: str
    tenant_id: str
    plan: str


class ApiKeyCreateReq(BaseModel):
    label: str = ""


class ApiKeyResp(BaseModel):
    key_id: str
    label: str
    env: str
    created_at: datetime
    disabled: bool
    # Raw key only returned on create — never again.
    raw_key: str | None = None


# --- deps ---------------------------------------------------------------
def _store(request: Request) -> TenantStore:
    return request.app.state.tenant_store


def _jwt_key(request: Request) -> str:
    key = server_infra().jwt_signing_key
    if not key:
        raise HTTPException(500, "server misconfigured: MEMNEX_JWT_SIGNING_KEY unset")
    return key


async def tenant_from_jwt(
    authorization: Annotated[str, Header()] = "",
    request: Request = None,  # type: ignore[assignment]
) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        return verify_session_jwt(authorization[7:], _jwt_key(request))
    except AuthError as e:
        raise HTTPException(401, str(e)) from e


# --- routes ---------------------------------------------------------------
@router.post("/auth/register", response_model=TokenResp)
async def register(req: RegisterReq, request: Request) -> TokenResp:
    store = _store(request)
    try:
        tenant = store.register(req.email, req.password)
    except AuthError as e:
        raise HTTPException(400, str(e)) from e
    jwt = issue_session_jwt(tenant.tenant_id, _jwt_key(request))
    return TokenResp(session_jwt=jwt, tenant_id=tenant.tenant_id, plan=tenant.plan)


@router.post("/auth/login", response_model=TokenResp)
async def login(req: LoginReq, request: Request) -> TokenResp:
    store = _store(request)
    try:
        tenant = store.login(req.email, req.password)
    except AuthError as e:
        raise HTTPException(401, str(e)) from e
    jwt = issue_session_jwt(tenant.tenant_id, _jwt_key(request))
    return TokenResp(session_jwt=jwt, tenant_id=tenant.tenant_id, plan=tenant.plan)


@router.post("/api-keys", response_model=ApiKeyResp)
async def create_api_key(
    req: ApiKeyCreateReq,
    request: Request,
    tenant_id: Annotated[str, Depends(tenant_from_jwt)],
) -> ApiKeyResp:
    store = _store(request)
    try:
        raw, meta = store.add_key(tenant_id, label=req.label)
    except AuthError as e:
        raise HTTPException(400, str(e)) from e
    return ApiKeyResp(
        key_id=meta.key_id, label=meta.label, env=meta.env,
        created_at=meta.created_at, disabled=meta.disabled,
        raw_key=raw,
    )


@router.get("/api-keys", response_model=list[ApiKeyResp])
async def list_api_keys(
    request: Request,
    tenant_id: Annotated[str, Depends(tenant_from_jwt)],
) -> list[ApiKeyResp]:
    store = _store(request)
    return [
        ApiKeyResp(
            key_id=k.key_id, label=k.label, env=k.env,
            created_at=k.created_at, disabled=k.disabled,
        )
        for k in store.all_keys(tenant_id)
    ]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    request: Request,
    tenant_id: Annotated[str, Depends(tenant_from_jwt)],
) -> None:
    store = _store(request)
    try:
        store.revoke_key(tenant_id, key_id)
    except AuthError as e:
        raise HTTPException(404, str(e)) from e


def mount_saas(app, store: TenantStore | None = None) -> TenantStore:
    """Attach SaaS routes + inject a shared TenantStore."""
    store = store or TenantStore()
    app.state.tenant_store = store
    app.include_router(router, prefix="/api/v1")
    return store
