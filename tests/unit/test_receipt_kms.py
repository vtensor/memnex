"""Pluggable signer for audit receipts (KMS / HSM hook)."""
from __future__ import annotations

import hashlib

from memnex.audit.receipts import set_signer, sign_receipt, verify_receipt


def test_default_no_key_still_tamper_evident(monkeypatch):
    monkeypatch.delenv("MEMNEX_AUDIT_KEY", raising=False)
    set_signer(None)
    r = sign_receipt("write", "t", "c", {"x": 1}).to_dict()
    assert r["mac"] is None
    assert verify_receipt(r)  # digest-only verify still works

    # Tampering the payload breaks verification.
    r["payload"] = {"x": 2}
    assert not verify_receipt(r)


def test_custom_kms_signer_and_verifier(monkeypatch):
    """Simulate a KMS: signer + verifier are two independent callables."""
    kms_key = b"SIMULATED-KMS-KEY"

    def kms_sign(body: bytes) -> str:
        import hmac
        return hmac.new(kms_key, body, hashlib.sha256).hexdigest()

    def kms_verify(body: bytes, signature_hex: str) -> bool:
        import hmac
        expected = hmac.new(kms_key, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_hex)

    set_signer(kms_sign)
    try:
        r = sign_receipt("write", "t", "c", {"x": 1}).to_dict()
        assert r["mac"] is not None
        assert verify_receipt(r, verifier=kms_verify)

        # Wrong verifier rejects.
        def bad_verify(body: bytes, sig: str) -> bool:
            return False

        assert not verify_receipt(r, verifier=bad_verify)
    finally:
        set_signer(None)
