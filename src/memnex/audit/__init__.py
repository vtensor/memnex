"""Audit layer.

- Signed receipts for every write + delete + export (sha256 of a canonical
  payload). Compliance teams archive these.
- :func:`trace` maps a chunk of agent output back to the source
  ``memory_id`` list, so "why did the agent say X?" has a concrete answer.
"""
from memnex.audit.receipts import Receipt, sign_receipt, verify_receipt
from memnex.audit.trace import trace_output

__all__ = ["Receipt", "sign_receipt", "verify_receipt", "trace_output"]
