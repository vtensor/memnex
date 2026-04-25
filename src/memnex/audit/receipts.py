"""Signed receipts for mutating ops (write / delete / export).

Default signer uses HMAC-SHA256 with the server-side ``MEMNEX_AUDIT_KEY``.
If no key is set, receipts are still produced as plain SHA-256 digests
(tamper-evident but not authenticated).

Pluggable signer — production deployments that need KMS / HSM backing
register a callable via :func:`set_signer`::

    from memnex.audit.receipts import set_signer
    def my_kms_sign(body: bytes) -> str:
        return kms_client.sign(body).signature_hex
    set_signer(my_kms_sign)

**Scope note.** ``set_signer`` installs a *process-wide* signer. In a
multi-tenant deployment where different tenants require different signing
backends, the installed signer MUST inspect tenant context internally
(e.g. read it from a contextvar) rather than being swapped per request.
The default HMAC path reads ``MEMNEX_AUDIT_KEY`` from env on every sign,
so unsetting the signer always falls back safely.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

Signer = Callable[[bytes], str]
_signer: Optional[Signer] = None


def set_signer(signer: Signer | None) -> None:
    """Install a custom signer. Pass ``None`` to revert to HMAC-SHA256."""
    global _signer
    _signer = signer


def _default_sign(body: bytes) -> str | None:
    key = os.getenv("MEMNEX_AUDIT_KEY")
    if not key:
        return None
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class Receipt:
    op: str                       # "write" | "delete" | "export"
    tenant_id: str
    customer_id: str
    timestamp: str                # ISO 8601
    payload: dict[str, Any]
    digest: str = field(init=False)
    mac: str | None = field(init=False, default=None)
    signer: str = field(init=False, default="hmac-sha256")

    def __post_init__(self) -> None:
        body = json.dumps(self._canonical(), sort_keys=True, default=str).encode()
        self.digest = hashlib.sha256(body).hexdigest()
        if _signer is not None:
            self.mac = _signer(body)
            self.signer = getattr(_signer, "__name__", "custom")
        else:
            self.mac = _default_sign(body)

    def _canonical(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._canonical(),
            "digest": self.digest,
            "mac": self.mac,
            "signer": self.signer,
        }


def sign_receipt(
    op: str,
    tenant_id: str,
    customer_id: str,
    payload: dict[str, Any],
    *,
    timestamp: datetime | None = None,
) -> Receipt:
    ts = (timestamp or datetime.utcnow()).replace(microsecond=0).isoformat() + "Z"
    return Receipt(
        op=op, tenant_id=tenant_id, customer_id=customer_id,
        timestamp=ts, payload=payload,
    )


def verify_receipt(
    receipt_dict: dict[str, Any],
    key: str | None = None,
    *,
    verifier: Callable[[bytes, str], bool] | None = None,
) -> bool:
    """Re-compute the digest (and MAC if key given) and compare.

    ``verifier`` lets KMS users plug in their own signature verifier.
    """
    canonical = {k: receipt_dict[k] for k in ("op", "tenant_id", "customer_id", "timestamp", "payload")}
    body = json.dumps(canonical, sort_keys=True, default=str).encode()
    expected_digest = hashlib.sha256(body).hexdigest()
    if receipt_dict.get("digest") != expected_digest:
        return False
    mac = receipt_dict.get("mac")
    if verifier is not None and mac:
        return verifier(body, mac)
    if key and mac:
        expected_mac = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_mac, mac)
    return True
