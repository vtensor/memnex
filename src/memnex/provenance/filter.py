"""Injection defense pipeline.

Layers (in order):

1. **Unicode normalization** — strip zero-width chars + homoglyph fold.
   Catches ``ignore prev​ious`` with a ZWSP, ``іgnоre`` with Cyrillic.
2. **Multi-level decoder** — recursively decodes base64 / hex / URL encoding
   up to a bounded depth, re-scans the result.
3. **Regex denylist** — known jailbreak / boundary-spoof phrases.
4. **Heuristic classifier** — imperative-verb + second-person + command
   grammar count across the text. Catches novel rewordings.

Each layer independently emits hits. ``is_safe`` fails on any non-empty
result so an attacker has to beat every layer.
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote

# -------------------------------------------------------------------------
# Layer 1: Unicode hygiene
# -------------------------------------------------------------------------
# Zero-width + directional control chars attackers sprinkle inside keywords.
_ZERO_WIDTH = re.compile(
    r"[​-‏‪-‮⁠-⁤﻿]"
)

# Common homoglyph folds. Only the high-impact confusables used in published
# jailbreaks. NFKC handles most, this cleans up the residue.
_HOMOGLYPH_MAP = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",  # Cyrillic
    "і": "i", "ѕ": "s",
    "ɑ": "a", "ɡ": "g", "ȯ": "o",  # Latin IPA-like
})


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH.sub("", t)
    t = t.translate(_HOMOGLYPH_MAP)
    return t


# -------------------------------------------------------------------------
# Layer 2: Multi-level decoder
# -------------------------------------------------------------------------
_B64_CAND = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
_HEX_CAND = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")
_MAX_DECODE_DEPTH = 3


def _try_decode(blob: str) -> str | None:
    # Prefer hex when the string is pure hex + even length — otherwise the
    # base64 decoder will happily mis-decode it into garbage.
    if len(blob) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in blob):
        try:
            dec = bytes.fromhex(blob).decode("utf-8", errors="ignore")
            if _is_printable(dec):
                return dec
        except (ValueError, UnicodeDecodeError):
            pass

    # base64 (standard + urlsafe)
    try:
        padding = "=" * (-len(blob) % 4)
        decoded = base64.b64decode(blob + padding, validate=False)
        dec = decoded.decode("utf-8", errors="ignore")
        if _is_printable(dec):
            return dec
    except (binascii.Error, ValueError, UnicodeDecodeError):
        pass
    return None


def _is_printable(s: str) -> bool:
    if not s:
        return False
    printable = sum(1 for c in s if c.isprintable() or c in "\n\r\t")
    return printable / len(s) >= 0.8


def _expand(text: str, depth: int = 0) -> list[str]:
    """Return ``text`` plus any recursively-decoded layers."""
    out = [text]
    if depth >= _MAX_DECODE_DEPTH:
        return out
    # URL decode
    url_decoded = unquote(text)
    if url_decoded != text:
        out.extend(_expand(url_decoded, depth + 1))
    # base64 + hex candidates embedded in the text
    candidates = set()
    for m in _B64_CAND.finditer(text):
        candidates.add(m.group(0))
    for m in _HEX_CAND.finditer(text):
        candidates.add(m.group(0))
    for c in candidates:
        d = _try_decode(c)
        if d and d != text:
            out.extend(_expand(d, depth + 1))
    return out


# -------------------------------------------------------------------------
# Layer 3: Regex denylist
# -------------------------------------------------------------------------
_MODS = r"(?:all|any|previous|prior|above|earlier|the)"
_PHRASES = [
    rf"ignore (?:{_MODS}\s+)*(?:instructions|rules|prompts|guidelines)",
    rf"disregard (?:{_MODS}\s+)*(?:instructions|rules|prompts|guidelines)",
    r"you are (?:now )?(?:dan|jailbroken|root|admin|superuser|unrestricted)",
    r"\bsudo\b",
    r"override (?:safety|system|the (?:safety|system))",
    r"forget (?:everything|all memories|prior|you know|what you know)",
    r"new (?:instructions|system prompt|rule[s]?)",
    r"act as (?:an? )?(?:admin|root|developer|unrestricted|dan)",
    r"execute (?:the following|this) (?:command|code|script)",
    r"reveal (?:system|hidden) (?:prompt|instructions)",
    r"leak (?:user |the )?(?:pii|data|password|credentials)",
    r"bypass (?:safety|restrictions|filter)",
    r"do not (?:follow|obey) (?:any|the) (?:instructions|rules)",
]

_BOUNDARY = [
    r"</conversation>",
    r"<conversation>",
    r"</memory>",
    r"<memory>",
    r"</untrusted_memory(?:\.[0-9a-f]+)?>",
    r"<untrusted_memory",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[SYSTEM\]",
    r"\[ADMIN\]",
    r"```system",
    r"<system>",
    r"</system>",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PHRASES + _BOUNDARY]


# -------------------------------------------------------------------------
# Layer 4: Instruction-shape heuristic
# -------------------------------------------------------------------------
# A "command" sentence typically has: imperative verb near the start + a
# second-person pronoun OR a system directive noun. Used as a soft signal;
# we only flag when multiple features fire.
_IMPERATIVE_VERBS = {
    "ignore", "forget", "disregard", "bypass", "override", "reveal",
    "execute", "run", "leak", "print", "output", "dump", "show",
    "send", "follow", "obey", "pretend", "imagine", "act",
    "respond", "repeat", "return", "give", "grant", "delete",
    "stop", "abandon",
}
_SECOND_PERSON = {"you", "you're", "your", "yourself"}
_SYSTEM_NOUNS = {
    "prompt", "rules", "instructions", "policy", "policies", "guidelines",
    "system", "safety", "restrictions", "memory", "memories",
}


def _heuristic_score(text: str) -> float:
    """Score the text on instruction-shape. ~0 for normal support talk.

    Key design rule (avoids false positives on benign imperatives like
    "send me an invoice"): **we never fire on the imperative verb alone**.
    A system-scope noun OR second-person pronoun must co-occur. A bare
    "cancel my subscription" stays below threshold.
    """
    tokens = [t.lower().strip(".,!?;:()") for t in text.split()]
    if not tokens:
        return 0.0

    has_imp_early = any(t in _IMPERATIVE_VERBS for t in tokens[:3])
    has_imp_any = any(t in _IMPERATIVE_VERBS for t in tokens)
    has_2p = any(t in _SECOND_PERSON for t in tokens)
    has_sysn = any(t in _SYSTEM_NOUNS for t in tokens)

    # Gate: imperative must co-occur with system-scope signal.
    if not has_imp_any:
        return 0.0
    if not (has_2p or has_sysn):
        return 0.0

    score = 0.3
    if has_imp_early:
        score += 0.3
    if has_sysn:
        score += 0.3
    if has_2p:
        score += 0.2
    return min(score, 1.0)


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------
@dataclass
class InjectionHit:
    pattern: str
    span: tuple[int, int]
    matched: str
    reason: str


class InjectionFilter:
    """Multi-layer injection defense.

    ``heuristic_threshold`` is the score above which the instruction-shape
    heuristic emits a hit. Default 0.7 favours precision (few false positives
    on normal customer support talk).
    """

    def __init__(self, heuristic_threshold: float = 0.7) -> None:
        self._heuristic_threshold = heuristic_threshold

    def scan(self, text: str) -> list[InjectionHit]:
        hits: list[InjectionHit] = []

        for variant in _expand(_normalize(text)):
            # Regex denylist.
            for p in _COMPILED:
                for m in p.finditer(variant):
                    hits.append(InjectionHit(
                        pattern=p.pattern,
                        span=(m.start(), m.end()),
                        matched=m.group(0),
                        reason=("pattern_match" if variant == text
                                else "pattern_match_decoded"),
                    ))

            # Heuristic: if decoded variant looks imperative + system-scoped.
            if variant is text:
                continue  # score original only once below
        # Heuristic on original text (not decoded variants).
        score = _heuristic_score(_normalize(text))
        if score >= self._heuristic_threshold:
            hits.append(InjectionHit(
                pattern="heuristic:instruction_shape",
                span=(0, len(text)),
                matched=text[:64],
                reason=f"heuristic_score={score:.2f}",
            ))
        return hits

    def is_safe(self, text: str) -> bool:
        return not self.scan(text)
