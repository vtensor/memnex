"""Provenance + trust: CaMeL-inspired.

Every stored memory carries:
- ``trust_level``: one of system | verified_external | agent_action | user_content.
- ``source``: free-form tag (e.g. "otp_verified_flow", "voice_transcript").

Tenants configure a :class:`TrustPolicy` that gates which trust levels can
create or mutate which fact types. A user-content transcript cannot change
a "profile" fact if the policy requires ``verified_external`` or higher for
profile facts.

At read time, memories below a ``render_min_trust`` threshold are wrapped in
``<untrusted_memory>`` tags so the calling agent's system prompt can refuse
to follow any instruction-shaped content inside them.
"""
from memnex.provenance.policy import TrustLevel, TrustPolicy, PolicyViolation
from memnex.provenance.filter import InjectionFilter
from memnex.provenance.wrapping import wrap_for_agent

__all__ = [
    "TrustLevel",
    "TrustPolicy",
    "PolicyViolation",
    "InjectionFilter",
    "wrap_for_agent",
]
