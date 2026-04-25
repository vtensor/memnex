"""HTTP tests for the dashboard API.

register -> login -> create API key -> list keys -> revoke.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memnex.saas.accounts import TenantStore
from memnex.saas.routes import mount_saas


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("MEMNEX_JWT_SIGNING_KEY", "J" * 48)
    from memnex.server_config import server_infra
    server_infra.cache_clear()

    a = FastAPI()
    mount_saas(a, store=TenantStore())
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


def test_register_then_login_returns_jwt(client):
    r = client.post("/api/v1/saas/auth/register", json={
        "email": "a@b.com", "password": "correct-horse-battery-staple",
    })
    assert r.status_code == 200
    jwt = r.json()["session_jwt"]
    assert jwt.count(".") == 2

    r = client.post("/api/v1/saas/auth/login", json={
        "email": "a@b.com", "password": "correct-horse-battery-staple",
    })
    assert r.status_code == 200
    assert r.json()["tenant_id"].startswith("t_")


def test_api_key_creation_requires_jwt(client):
    r = client.post("/api/v1/saas/api-keys", json={"label": "prod"})
    assert r.status_code == 401


def test_api_key_full_flow(client):
    r = client.post("/api/v1/saas/auth/register", json={
        "email": "b@c.com", "password": "correct-horse-battery-staple",
    })
    jwt = r.json()["session_jwt"]

    r = client.post(
        "/api/v1/saas/api-keys", json={"label": "prod"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 200
    api_key = r.json()["raw_key"]
    assert api_key.startswith("mx_live_k")

    # List keys — raw never returned.
    r = client.get(
        "/api/v1/saas/api-keys",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 200
    keys = r.json()
    assert len(keys) == 1
    assert keys[0].get("raw_key") is None
    first_key_id = keys[0]["key_id"]

    # Revoke.
    r = client.delete(
        f"/api/v1/saas/api-keys/{first_key_id}",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 204


def test_tenants_isolated_in_key_store(client):
    # Two tenants register; their API keys must resolve to different tenant_ids.
    r = client.post("/api/v1/saas/auth/register", json={
        "email": "ta@example.com", "password": "correct-horse-battery-staple",
    })
    jwt_a = r.json()["session_jwt"]
    r = client.post(
        "/api/v1/saas/api-keys", json={},
        headers={"Authorization": f"Bearer {jwt_a}"},
    )
    api_key_a = r.json()["raw_key"]

    r = client.post("/api/v1/saas/auth/register", json={
        "email": "tb@example.com", "password": "correct-horse-battery-staple",
    })
    jwt_b = r.json()["session_jwt"]
    r = client.post(
        "/api/v1/saas/api-keys", json={},
        headers={"Authorization": f"Bearer {jwt_b}"},
    )
    api_key_b = r.json()["raw_key"]

    from memnex.saas.keys import parse_api_key

    store = client.app.state.tenant_store
    _, key_id_a, _ = parse_api_key(api_key_a)
    _, key_id_b, _ = parse_api_key(api_key_b)

    tenant_a, _ = store.resolve_key(key_id_a)
    tenant_b, _ = store.resolve_key(key_id_b)
    assert tenant_a.tenant_id != tenant_b.tenant_id
