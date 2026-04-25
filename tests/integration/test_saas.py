"""SaaS tests: accounts, JWTs, API keys.

No user_tokens — user_id is passed directly per MCP call, scoped by the
tenant derived from the API key.
"""
from __future__ import annotations

import pytest

from memnex.saas.accounts import (
    AuthError,
    TenantStore,
    issue_session_jwt,
    verify_session_jwt,
)
from memnex.saas.keys import generate_api_key, parse_api_key, verify_api_key


# ----- accounts -----------------------------------------------------------
def test_register_and_login_roundtrip():
    store = TenantStore()
    t = store.register("alice@example.com", "correct-horse-battery-staple")
    assert t.tenant_id.startswith("t_")
    logged = store.login("alice@example.com", "correct-horse-battery-staple")
    assert logged.tenant_id == t.tenant_id


def test_duplicate_registration_fails():
    store = TenantStore()
    store.register("dup@example.com", "correct-horse-battery-staple")
    with pytest.raises(AuthError):
        store.register("dup@example.com", "another-long-password-123")


def test_weak_password_rejected():
    store = TenantStore()
    with pytest.raises(AuthError):
        store.register("weak@example.com", "short")
    with pytest.raises(AuthError):
        store.register("weak2@example.com", "password")


def test_bad_email_rejected():
    store = TenantStore()
    with pytest.raises(AuthError):
        store.register("not-an-email", "correct-horse-battery-staple")


def test_login_wrong_password_fails():
    store = TenantStore()
    store.register("wrong@example.com", "correct-horse-battery-staple")
    with pytest.raises(AuthError):
        store.login("wrong@example.com", "wrong-password")


def test_session_jwt_roundtrip():
    jwt = issue_session_jwt("t_abc", jwt_signing_key="super-secret-jwt-key")
    sub = verify_session_jwt(jwt, jwt_signing_key="super-secret-jwt-key")
    assert sub == "t_abc"


def test_session_jwt_bad_signature():
    jwt = issue_session_jwt("t_abc", jwt_signing_key="key-a")
    with pytest.raises(AuthError):
        verify_session_jwt(jwt, jwt_signing_key="key-b")


# ----- api keys -----------------------------------------------------------
def test_api_key_format_and_verify():
    raw, meta = generate_api_key(tenant_id="t_xyz")
    assert raw.startswith("mx_live_k")
    env, key_id, _ = parse_api_key(raw)
    assert env == "live"
    assert key_id == meta.key_id
    assert verify_api_key(raw, meta)


def test_api_key_tamper_fails():
    raw, meta = generate_api_key(tenant_id="t_xyz")
    tampered = raw[:-5] + "AAAAA"
    assert not verify_api_key(tampered, meta)


def test_api_key_disable_stops_verify():
    raw, meta = generate_api_key(tenant_id="t_xyz")
    meta.disabled = True
    assert not verify_api_key(raw, meta)


def test_api_key_crosses_tenants_fails():
    _, meta_a = generate_api_key(tenant_id="t_a")
    raw_b, _ = generate_api_key(tenant_id="t_b")
    assert not verify_api_key(raw_b, meta_a)


def test_mcp_tool_schemas_take_user_id_not_tokens():
    """MCP tools expose user_id as a plain required param (no token dance)."""
    from memnex.mcp.tools import TOOL_SCHEMAS
    for schema in TOOL_SCHEMAS:
        props = schema["inputSchema"]["properties"]
        assert "user_id" in props, f"{schema['name']} missing user_id"
        assert "user_token" not in props, f"{schema['name']} still has user_token"
        assert "identifier" not in props, f"{schema['name']} leaks identifier"
