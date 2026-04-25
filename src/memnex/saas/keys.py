"""Tenant API keys.

An API key is the single secret a tenant pastes into their MCP config as
``MEMNEX_SECRET_KEY``. It maps to ``tenant_id``. That's it.

Format: ``mx_<env>_<key_id>_<random>``

- ``env``: ``live`` or ``test`` (lets us separate prod + staging traffic).
- ``key_id``: short public prefix so ops can identify a key in logs without
  the secret part.
- ``random``: 32 bytes of base64url entropy.

Storage:
- We never store the raw key. We store ``(key_id, hash(key))`` like a
  password. Revoking = disabling the row.
- On verify, we look up by ``key_id`` prefix then constant-time compare the
  hash. O(1) lookup, no secret exposure.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Env = Literal["live", "test"]


@dataclass
class ApiKey:
    key_id: str           # public prefix, e.g. "k_a3f9b2"
    tenant_id: str
    env: Env
    hashed_secret: str    # hex(sha256(raw_secret))
    created_at: datetime
    last_used_at: datetime | None
    disabled: bool = False
    label: str = ""


def _random_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def _hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key(
    *,
    tenant_id: str,
    env: Env = "live",
    label: str = "",
) -> tuple[str, ApiKey]:
    """Mint a new API key. Returns ``(raw_key, metadata)``.

    The raw key is shown ONCE to the tenant; we only store the metadata +
    hash.
    """
    key_id = "k" + secrets.token_hex(4)  # no inner underscore -> clean parse
    raw_secret = _random_secret()
    raw_key = f"mx_{env}_{key_id}_{raw_secret}"
    meta = ApiKey(
        key_id=key_id,
        tenant_id=tenant_id,
        env=env,
        hashed_secret=_hash_secret(raw_secret),
        created_at=datetime.utcnow(),
        last_used_at=None,
        disabled=False,
        label=label,
    )
    return raw_key, meta


def parse_api_key(raw_key: str) -> tuple[Env, str, str]:
    """Return ``(env, key_id, raw_secret)`` or raise."""
    if not raw_key.startswith("mx_"):
        raise ValueError("bad prefix")
    parts = raw_key.split("_", 3)
    if len(parts) != 4:
        raise ValueError("malformed key")
    _, env, key_id, raw_secret = parts
    if env not in ("live", "test"):
        raise ValueError("bad env")
    if not key_id.startswith("k"):
        raise ValueError("bad key_id")
    return env, key_id, raw_secret  # type: ignore[return-value]


def verify_api_key(raw_key: str, stored: ApiKey) -> bool:
    """Constant-time verify the raw key against stored metadata."""
    try:
        env, key_id, raw_secret = parse_api_key(raw_key)
    except ValueError:
        return False
    if stored.disabled:
        return False
    if stored.env != env or stored.key_id != key_id:
        return False
    return hmac.compare_digest(stored.hashed_secret, _hash_secret(raw_secret))
