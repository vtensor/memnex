"""PII masking at write time.

Three strategies:

- ``redact``: replace with ``[FIELD]`` placeholder (lossy, but safe).
- ``hash``: replace with ``[FIELD:<hash>]``. Lets us match identical values
  later without storing plaintext.
- ``encrypt``: reversible only if a key is provided. Out of scope for the
  default build — we fall back to hash if no key is configured.
"""
from __future__ import annotations

import hashlib

from memnex.config import MemnexConfig
from memnex.memory.models import Fact
from memnex.privacy.pii_detector import PIIHit, build_detector


class PIIMasker:
    def __init__(self, config: MemnexConfig) -> None:
        self._cfg = config
        self._detector = build_detector(config)

    def mask_fact(self, fact: Fact) -> Fact:
        if not self._cfg.pii_detection:
            return fact
        masked_text, hits = self._mask(fact.fact)
        if not hits:
            return fact
        pii_fields = sorted({h.field for h in hits})
        # Attach pii_fields via model_copy (Fact doesn't declare it — we stash
        # it in a private attr read by MemoryManager).
        new = fact.model_copy(update={"fact": masked_text})
        object.__setattr__(new, "pii_fields", pii_fields)  # type: ignore[misc]
        return new

    def mask_text(self, text: str) -> str:
        return self._mask(text)[0]

    def _mask(self, text: str) -> tuple[str, list[PIIHit]]:
        hits = self._detector.detect(text)
        if not hits:
            return text, []
        # Apply replacements right-to-left so indices stay valid.
        out = text
        for h in sorted(hits, key=lambda x: x.start, reverse=True):
            repl = self._render(h)
            out = out[: h.start] + repl + out[h.end:]
        return out, hits

    def _render(self, hit: PIIHit) -> str:
        if self._cfg.pii_mask_strategy == "redact":
            return f"[{hit.field.upper()}]"
        if self._cfg.pii_mask_strategy == "encrypt":
            # No key wired in — fall through to hash.
            pass
        digest = hashlib.blake2b(hit.value.encode(), digest_size=6).hexdigest()
        return f"[{hit.field.upper()}:{digest}]"
