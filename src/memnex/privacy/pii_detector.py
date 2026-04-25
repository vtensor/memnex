"""PII detection.

Regex-first: covers the high-signal regulated identifiers. Presidio is an
*optional* second layer gated to REGULATED entities only — it will NOT detect
names, locations, dates, or organizations. Those are precisely the kind of
facts a memory product is supposed to remember.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from memnex.config import MemnexConfig

logger = logging.getLogger(__name__)

_PATTERNS: dict[str, re.Pattern[str]] = {
    # Aadhaar: 12 digits, optionally in 4-4-4 groups.
    "aadhaar": re.compile(r"\b(?:\d{4}[\s-]?){2}\d{4}\b"),
    # PAN: 5 letters, 4 digits, 1 letter.
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    # Credit card: 13-19 digits, optionally space/dash separated.
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    # Email.
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    # Phone: +country with optional separators, 7+ digits total.
    "phone": re.compile(r"\+?\d[\d\s\-().]{7,}\d"),
    # Date of birth (yyyy-mm-dd, dd/mm/yyyy, dd-mm-yyyy). Off by default —
    # only mask when the tenant asks for it.
    "dob": re.compile(
        r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2}\b"
    ),
    # OTP: 4-8 digit code near "otp"/"code"/"pin".
    "otp": re.compile(r"\b(?:otp|code|pin)\D{0,10}(\d{4,8})\b", re.IGNORECASE),
    # Bank account: context-anchored ("a/c", "account no.", etc.) + 9-18 digits.
    # Pure digits with no context are too ambiguous to mask safely.
    "bank_account": re.compile(
        r"\b(?:a\/c|acc(?:oun)?t|account)\s*(?:no\.?|number|#)?\s*:?\s*(\d{9,18})\b",
        re.IGNORECASE,
    ),
    # IBAN: 2 letters + 2 digits + 4-30 alphanumerics (simplified).
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    # US SSN: XXX-XX-XXXX.
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}


@dataclass
class PIIHit:
    field: str
    value: str
    start: int
    end: int


class Detector(Protocol):
    def detect(self, text: str) -> list[PIIHit]: ...


class PIIDetector:
    """Regex-based detector. Fast, dependency-free, industry-standard for
    regulated identifiers."""

    def __init__(self, fields: list[str] | None = None) -> None:
        self._fields = fields or list(_PATTERNS.keys())

    def detect(self, text: str) -> list[PIIHit]:
        hits: list[PIIHit] = []
        for field in self._fields:
            pattern = _PATTERNS.get(field)
            if not pattern:
                continue
            for m in pattern.finditer(text):
                hits.append(PIIHit(field=field, value=m.group(0), start=m.start(), end=m.end()))
        return hits


# Presidio entity types we are willing to act on. Deliberately excludes:
#   PERSON, LOCATION, NRP, DATE_TIME, ORGANIZATION, URL, MEDICAL_LICENSE, ...
# Those are either useful memory content (names, places, preferences) or noisy.
_PRESIDIO_ALLOWED: dict[str, str] = {
    "CREDIT_CARD": "credit_card",
    "EMAIL_ADDRESS": "email",
    "PHONE_NUMBER": "phone",
    "IBAN_CODE": "iban",
    "US_SSN": "ssn",
    "US_BANK_NUMBER": "bank_account",
    "IN_AADHAAR": "aadhaar",
    "IN_PAN": "pan",
    "CRYPTO": "crypto",
}


class PresidioDetector:
    """Optional Presidio-backed detector, restricted to regulated entities.

    This is the "industry grade" layer: context-aware recognition (e.g. a bare
    16-digit number next to the word "card" will match even if a regex would
    also catch it; names, locations, and dates are NOT detected by design)."""

    def __init__(self, fields: list[str]) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine
        except ImportError as e:
            raise ImportError(
                "Presidio requires `pip install memnex[privacy-presidio]`."
            ) from e
        self._analyzer = AnalyzerEngine()
        requested = set(fields)
        self._entities = [e for e, f in _PRESIDIO_ALLOWED.items() if f in requested]

    def detect(self, text: str) -> list[PIIHit]:
        if not self._entities:
            return []
        results = self._analyzer.analyze(text=text, entities=self._entities, language="en")
        hits: list[PIIHit] = []
        for r in results:
            field = _PRESIDIO_ALLOWED.get(r.entity_type)
            if not field:
                continue
            hits.append(
                PIIHit(field=field, value=text[r.start : r.end], start=r.start, end=r.end)
            )
        return hits


class CompositeDetector:
    """Regex first, Presidio second. Dedupes overlapping spans."""

    def __init__(self, primary: Detector, secondary: Detector) -> None:
        self._primary = primary
        self._secondary = secondary

    def detect(self, text: str) -> list[PIIHit]:
        hits = [*self._primary.detect(text), *self._secondary.detect(text)]
        return _dedupe_overlaps(hits)


def _dedupe_overlaps(hits: list[PIIHit]) -> list[PIIHit]:
    # Prefer earlier-starting, wider-spanning hits; drop anything that overlaps
    # an already-kept span.
    hits = sorted(hits, key=lambda h: (h.start, -(h.end - h.start)))
    kept: list[PIIHit] = []
    for h in hits:
        if any(h.start < k.end and k.start < h.end for k in kept):
            continue
        kept.append(h)
    return kept


def build_detector(config: MemnexConfig) -> Detector:
    regex = PIIDetector(config.pii_fields_to_mask)
    if not config.pii_use_presidio:
        return regex
    try:
        presidio = PresidioDetector(config.pii_fields_to_mask)
    except ImportError as e:
        logger.warning(
            "pii_use_presidio=True but Presidio is not installed (%s). "
            "Falling back to regex-only detection.",
            e,
        )
        return regex
    return CompositeDetector(regex, presidio)
