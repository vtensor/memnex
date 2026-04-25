"""Tenant accounts: register + login.

Passwords hashed with PBKDF2-SHA256 (stdlib only; tenants who want argon2 or
bcrypt can swap the two hashing functions below). Sessions are JWT-style
tokens signed with the server's JWT key.

Backed by a simple in-memory store here. The Postgres store will mirror
this interface in production.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from memnex.saas.keys import ApiKey, generate_api_key

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
_MIN_PW_LEN = 10
_PBKDF2_ITERS = 200_000
_SESSION_TTL = 12 * 3600  # 12 hours


class AuthError(Exception):
    pass


@dataclass
class Tenant:
    tenant_id: str
    email: str
    password_hash: str
    password_salt: str
    created_at: datetime
    plan: str = "free"  # free | pro | enterprise
    api_keys: list[ApiKey] = field(default_factory=list)
    disabled: bool = False


def _hash_password(password: str, salt: str) -> str:
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return h.hex()


def _check_password(password: str, salt: str, expected_hash: str) -> bool:
    got = _hash_password(password, salt)
    return hmac.compare_digest(got, expected_hash)


def _validate_password(password: str) -> None:
    if len(password) < _MIN_PW_LEN:
        raise AuthError(f"password must be >= {_MIN_PW_LEN} chars")
    if password.lower() in {"password", "password1", "admin123"}:
        raise AuthError("password too common")


def _validate_email(email: str) -> None:
    if not _EMAIL_RE.match(email):
        raise AuthError("bad email")


# --- in-memory store (replace with Postgres in production) ---
class TenantStore:
    def __init__(self) -> None:
        self._by_email: dict[str, Tenant] = {}
        self._by_id: dict[str, Tenant] = {}
        self._by_key_id: dict[str, tuple[Tenant, ApiKey]] = {}

    def register(self, email: str, password: str) -> Tenant:
        _validate_email(email)
        _validate_password(password)
        if email.lower() in self._by_email:
            raise AuthError("email already registered")
        salt = secrets.token_hex(16)
        tenant = Tenant(
            tenant_id="t_" + secrets.token_hex(8),
            email=email.lower(),
            password_hash=_hash_password(password, salt),
            password_salt=salt,
            created_at=datetime.now(timezone.utc),
        )
        self._by_email[tenant.email] = tenant
        self._by_id[tenant.tenant_id] = tenant
        return tenant

    def login(self, email: str, password: str) -> Tenant:
        t = self._by_email.get(email.lower())
        if not t or t.disabled:
            raise AuthError("invalid credentials")
        if not _check_password(password, t.password_salt, t.password_hash):
            raise AuthError("invalid credentials")
        return t

    def get(self, tenant_id: str) -> Tenant | None:
        return self._by_id.get(tenant_id)

    def add_key(self, tenant_id: str, label: str = "") -> tuple[str, ApiKey]:
        t = self._by_id.get(tenant_id)
        if not t or t.disabled:
            raise AuthError("unknown tenant")
        raw, meta = generate_api_key(tenant_id=tenant_id, label=label)
        t.api_keys.append(meta)
        self._by_key_id[meta.key_id] = (t, meta)
        return raw, meta

    def revoke_key(self, tenant_id: str, key_id: str) -> None:
        t = self._by_id.get(tenant_id)
        if not t:
            raise AuthError("unknown tenant")
        for k in t.api_keys:
            if k.key_id == key_id:
                k.disabled = True
                return
        raise AuthError("unknown key")

    def resolve_key(self, key_id: str) -> tuple[Tenant, ApiKey] | None:
        return self._by_key_id.get(key_id)

    def all_keys(self, tenant_id: str) -> Iterable[ApiKey]:
        t = self._by_id.get(tenant_id)
        return t.api_keys if t else []


# --- JWT session ---
def issue_session_jwt(tenant_id: str, jwt_signing_key: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "sub": tenant_id,
        "iat": now,
        "exp": now + _SESSION_TTL,
        "scope": "dashboard",
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    c = _b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    body = f"{h}.{c}".encode()
    sig = _b64url(
        hmac.new(jwt_signing_key.encode(), body, hashlib.sha256).digest()
    )
    return f"{h}.{c}.{sig}"


def verify_session_jwt(token: str, jwt_signing_key: str) -> str:
    """Return ``tenant_id`` or raise."""
    try:
        h, c, s = token.split(".")
    except ValueError as e:
        raise AuthError("malformed jwt") from e
    body = f"{h}.{c}".encode()
    expected = _b64url(
        hmac.new(jwt_signing_key.encode(), body, hashlib.sha256).digest()
    )
    if not hmac.compare_digest(s, expected):
        raise AuthError("bad signature")
    claims = json.loads(_b64url_decode(c))
    now = int(datetime.now(timezone.utc).timestamp())
    if now > int(claims["exp"]):
        raise AuthError("session expired")
    return str(claims["sub"])


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)
