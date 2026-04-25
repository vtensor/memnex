"""Hybrid fact extractor.

Three tiers, in order, short-circuit on confidence:

1. **Rules** — regex patterns (fast, high precision on exact matches).
2. **Fuzzy** — rapidfuzz token-set ratio against a synonym dictionary.
   Handles typos ("refnd" ≈ "refund") and surface variants.
3. **Encoder** — sentence-transformers `all-MiniLM-L6-v2` against
   seed intent/issue/resolution templates. Handles paraphrases
   ("money back please" → refund intent). Optional: requires
   ``pip install memnex[extractor-ml]``.
4. **LLM** — fallback for residue if configured.

For each sentence, we take the highest-confidence classification across
tiers. Rule-based hits win ties because they're cheapest to reproduce.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from memnex.memory.extractor import (
    RuleBasedExtractor,
    _collapse_ws,
    _sentences,
    _ENTITY_MONEY,
    _ENTITY_ORDER,
    _FILLER,
    _GREETING,
)
from memnex.memory.models import Fact, FactType

try:
    from rapidfuzz import fuzz, process
    _HAS_FUZZ = True
except ImportError:  # pragma: no cover
    _HAS_FUZZ = False


# Synonym dictionary — keys are fact types, values are phrases the user
# might say (including typos, slang, short forms). Expandable per tenant.
_SYNONYMS: dict[FactType, list[str]] = {
    "intent": [
        "refund", "refnd", "money back", "return my money", "cancel order",
        "cancel my order", "stop subscription", "unsubscribe", "close account",
        "upgrade plan", "downgrade", "change address", "reschedule delivery",
        "reschedule", "talk to human", "speak to agent", "escalate",
        "need help", "want help", "need support",
    ],
    "issue": [
        "damaged", "broken", "not working", "doesnt work", "doesn't work",
        "not delivered", "never arrived", "missing item", "wrong item",
        "leaking", "stopped working", "crashed", "error", "bug",
        "defective", "faulty", "busted", "cracked", "torn",
        "delayed", "late", "stuck in transit",
    ],
    "resolution": [
        "replacement accepted", "accepted replacement",
        "refund processed", "refund issued", "refunded",
        "issue resolved", "fixed", "working now", "replaced",
        "delivered", "shipped", "completed",
    ],
    "profile": [
        "customer since", "member since", "years with you",
        "premium plan", "basic plan", "enterprise plan",
        "speak english", "speak hindi", "prefer english",
    ],
    "preference": [
        "prefer morning", "prefer evening", "prefer email",
        "prefer sms", "prefer whatsapp", "call me",
        "do not call", "dont call", "no phone calls",
    ],
}


@dataclass
class HybridConfig:
    fuzzy_threshold: float = 82.0          # rapidfuzz 0-100 score
    encoder_threshold: float = 0.55         # cosine similarity 0-1
    use_encoder: bool = False               # opt-in (needs the model)
    encoder_model: str = "all-MiniLM-L6-v2"


class HybridExtractor:
    """Hybrid extractor. Drop-in replacement for RuleBasedExtractor."""

    def __init__(self, cfg: HybridConfig | None = None) -> None:
        self._cfg = cfg or HybridConfig()
        self._rules = RuleBasedExtractor()
        self._encoder = None
        self._template_vecs: dict[str, list] = {}
        if self._cfg.use_encoder:
            self._load_encoder()

    def _load_encoder(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            # Model not installed; silently disable encoder tier.
            self._cfg = HybridConfig(
                fuzzy_threshold=self._cfg.fuzzy_threshold,
                encoder_threshold=self._cfg.encoder_threshold,
                use_encoder=False,
                encoder_model=self._cfg.encoder_model,
            )
            return
        self._encoder = SentenceTransformer(self._cfg.encoder_model)
        for ftype, phrases in _SYNONYMS.items():
            self._template_vecs[ftype] = self._encoder.encode(
                phrases, normalize_embeddings=True
            )

    async def extract(self, text: str, *, channel: str) -> list[Fact]:
        out: list[Fact] = []
        for raw in _sentences(text):
            s = _FILLER.sub("", raw).strip().lstrip(",.;: ")
            if not s or _GREETING.match(s):
                continue

            # Tier 1: rules (already implemented in RuleBasedExtractor).
            tier1 = await self._rules.extract(s, channel=channel)
            rule_fact = tier1[0] if tier1 else None
            rule_is_generic = rule_fact is None or rule_fact.type == "event"

            # Tier 2: fuzzy match. Gives typo-tolerance.
            fuzzy_type, fuzzy_score = self._fuzzy_classify(s)

            # Tier 3: encoder (synonyms / paraphrases).
            enc_type, enc_score = (None, 0.0)
            if self._encoder is not None:
                enc_type, enc_score = self._encoder_classify(s)

            # Merge: rules are authoritative for specific types; tiers 2/3
            # upgrade generic "event" classifications.
            best_type: FactType | None = None
            confidence = 0.0

            if rule_fact and not rule_is_generic:
                best_type = rule_fact.type
                confidence = rule_fact.confidence
            elif enc_type and enc_score >= self._cfg.encoder_threshold:
                best_type = enc_type  # type: ignore[assignment]
                confidence = 0.6 + 0.35 * enc_score
            elif fuzzy_type and fuzzy_score >= self._cfg.fuzzy_threshold:
                best_type = fuzzy_type  # type: ignore[assignment]
                confidence = 0.55 + 0.4 * (fuzzy_score / 100.0)
            elif rule_fact:
                best_type = rule_fact.type  # generic event
                confidence = rule_fact.confidence
            else:
                continue

            entities = _extract_entities(s)
            out.append(Fact(
                fact=_collapse_ws(s),
                type=best_type,
                entities=entities,
                confidence=min(round(confidence, 3), 0.95),
            ))
        return out

    # ------------------------------------------------------------------
    def _fuzzy_classify(self, sentence: str) -> tuple[FactType | None, float]:
        if not _HAS_FUZZ:
            return None, 0.0
        best_type: FactType | None = None
        best_score = 0.0
        lower = sentence.lower()
        for ftype, phrases in _SYNONYMS.items():
            match = process.extractOne(
                lower, phrases, scorer=fuzz.token_set_ratio
            )
            if match is None:
                continue
            _, score, _ = match
            if score > best_score:
                best_score = score
                best_type = ftype
        return best_type, best_score

    def _encoder_classify(self, sentence: str) -> tuple[FactType | None, float]:
        import numpy as np
        vec = self._encoder.encode(sentence, normalize_embeddings=True)
        best_type: FactType | None = None
        best_score = 0.0
        for ftype, templates in self._template_vecs.items():
            sims = np.array(templates) @ np.asarray(vec)
            s = float(sims.max())
            if s > best_score:
                best_score = s
                best_type = ftype  # type: ignore[assignment]
        return best_type, best_score


def _extract_entities(s: str) -> list[str]:
    entities: list[str] = []
    for m in _ENTITY_ORDER.finditer(s):
        entities.append(f"order_{m.group(1)}")
    for m in _ENTITY_MONEY.finditer(s):
        entities.append(f"money_{m.group(0)}")
    return entities
