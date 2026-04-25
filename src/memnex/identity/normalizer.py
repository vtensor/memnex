"""Normalize channel identifiers to a canonical form.

The deterministic path in IdentityResolver hinges on this: two identifiers
only match if they normalize to the same string, so normalization has to be
idempotent and lossless. We use the ``phonenumbers`` library for phones to
handle Indian, international, and WhatsApp-prefixed formats uniformly.
"""
from __future__ import annotations

import re
from typing import Literal

try:
    import phonenumbers
except ImportError:  # pragma: no cover
    phonenumbers = None  # type: ignore[assignment]

IdentifierType = Literal[
    "phone", "email", "session_cookie", "app_user_id", "whatsapp_id", "sms_number"
]

_WA_PREFIX = re.compile(r"^wa:", re.IGNORECASE)
_WS = re.compile(r"\s+")
_PHONE_ALLOWED = re.compile(r"[^\d+]")


def infer_type(channel: str, identifier: str) -> IdentifierType:
    if channel == "whatsapp":
        return "whatsapp_id"
    if channel in {"voice", "sms"}:
        return "phone"
    if channel == "email":
        return "email"
    if channel == "web":
        return "session_cookie"
    if channel == "app":
        return "app_user_id"
    if "@" in identifier:
        return "email"
    if identifier.startswith("+") or identifier.startswith("wa:"):
        return "phone"
    return "app_user_id"


def normalize(channel: str, identifier: str, default_region: str = "IN") -> str:
    """Return the canonical form for ``(channel, identifier)``.

    - Phones and WhatsApp ids both normalize to E.164 digits without the '+'.
      So ``+91 92410 63955``, ``092-4106-3955``, and ``wa:919241063955``
      all collapse to ``919241063955``.
    - Emails lowercased, stripped.
    - Session cookies / app user ids passed through, trimmed.
    """
    if not identifier:
        raise ValueError("identifier must be non-empty")

    ident = identifier.strip()
    kind = infer_type(channel, ident)

    if kind == "email":
        return ident.lower()

    if kind in {"phone", "whatsapp_id", "sms_number"}:
        return _normalize_phone(ident, default_region)

    # session cookies / app user ids / anything else: trim whitespace only.
    return _WS.sub("", ident)


def _normalize_phone(raw: str, default_region: str) -> str:
    cleaned = _WA_PREFIX.sub("", raw).strip()
    if phonenumbers is not None:
        try:
            parsed = phonenumbers.parse(cleaned, default_region)
            if phonenumbers.is_possible_number(parsed):
                return f"{parsed.country_code}{parsed.national_number}"
        except Exception:
            pass
    # Fallback: strip everything except digits and a leading '+'.
    stripped = _PHONE_ALLOWED.sub("", cleaned)
    return stripped.lstrip("+")
