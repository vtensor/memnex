"""Trust levels + policy."""
from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field


class TrustLevel(IntEnum):
    """Ordered so ``>=`` comparisons make sense."""

    user_content = 1        # anything from the user side of the conversation
    agent_action = 2        # produced by an agent (still not fully trusted)
    verified_external = 3   # OTP / login / CRM-confirmed
    system = 4              # set by Memnex or an admin

    @classmethod
    def parse(cls, value: str | int | "TrustLevel") -> "TrustLevel":
        if isinstance(value, TrustLevel):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value]


FactType = Literal[
    "event", "intent", "profile", "preference", "issue", "resolution"
]


class PolicyViolation(Exception):
    """Raised when a write would violate the configured trust policy."""


class TrustPolicy(BaseModel):
    """Per-tenant policy: minimum trust level required to create each fact type.

    Defaults are deliberately strict on ``profile`` + ``preference`` (long-lived
    identity-like facts) and permissive on ``event`` / ``issue`` (in-session
    observations that can be overwritten freely).
    """

    min_trust: dict[str, int] = Field(
        default_factory=lambda: {
            # Profile + preference = long-lived identity-shaped facts. We
            # require verified_external by default because a malicious user
            # message should not be able to silently overwrite "user is on
            # the enterprise plan" or "user's language is Hindi".
            "profile":    int(TrustLevel.verified_external),
            "preference": int(TrustLevel.verified_external),
            # Everything else is in-session state; user content can set it.
            "resolution": int(TrustLevel.user_content),
            "intent":     int(TrustLevel.user_content),
            "issue":      int(TrustLevel.user_content),
            "event":      int(TrustLevel.user_content),
        }
    )

    # Trust levels *below* this are wrapped in <untrusted_memory> at read time.
    render_min_trust: int = int(TrustLevel.agent_action)

    # Deny-list patterns checked against every incoming fact text.
    reject_injection_patterns: bool = True

    def check(self, fact_type: str, trust: TrustLevel) -> None:
        required = self.min_trust.get(fact_type, int(TrustLevel.user_content))
        if int(trust) < required:
            raise PolicyViolation(
                f"fact_type={fact_type!r} requires trust >= "
                f"{TrustLevel(required).name} (got {trust.name})"
            )

    def is_trusted_for_render(self, trust: TrustLevel) -> bool:
        return int(trust) >= int(self.render_min_trust)
