"""Fact extraction.

Two implementations that share an interface:

- :class:`RuleBasedExtractor`: zero-dependency, fast, no LLM. Splits the
  transcript into sentences, filters greetings/fillers, classifies each by
  surface cues. Good enough for cost-sensitive deployments and is the default.
- :class:`LLMExtractor`: uses an LLM in JSON mode for richer structured
  extraction. Enabled by setting ``llm_provider`` in config.

If the library is used with ``facts=["..."]`` (pre-extracted), extractors are
skipped — the caller is already giving us structured facts.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from memnex.config import MemnexConfig
from memnex.memory.models import Fact, FactType

# Surface cues for rule-based classification.
_GREETING = re.compile(
    r"^(hi|hello|hey|namaste|good (morning|afternoon|evening)|thanks|thank you|ok|okay|yes|no|yeah|nope|bye|goodbye)[\.\!\? ]*$",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"\b(um+|uh+|er+|ah+|like|you know|i mean|basically|actually|literally)\b",
    re.IGNORECASE,
)
_INTENT_CUES = re.compile(
    r"\b(want|need|would like|looking for|please|refund|cancel|change|update|upgrade|downgrade|stop|start)\b",
    re.IGNORECASE,
)
_ISSUE_CUES = re.compile(
    r"\b(broken|damaged|not working|error|issue|problem|failed|stuck|can't|cannot|won't)\b",
    re.IGNORECASE,
)
_RESOLUTION_CUES = re.compile(
    r"\b(resolved|fixed|replaced|refunded|shipped|delivered|accepted|confirmed)\b",
    re.IGNORECASE,
)
_PROFILE_CUES = re.compile(
    r"\b(customer (for|since)|member|tenure|years? (old|customer)|live in|located in)\b",
    re.IGNORECASE,
)
_ENTITY_ORDER = re.compile(r"#?\b(?:order|inv(?:oice)?|ticket)[\s#]*([A-Z0-9\-]{3,})", re.IGNORECASE)
_ENTITY_MONEY = re.compile(r"[₹$€£]\s?\d[\d,]*(?:\.\d+)?")


class Extractor(ABC):
    @abstractmethod
    async def extract(self, text: str, *, channel: str) -> list[Fact]: ...


class RuleBasedExtractor(Extractor):
    async def extract(self, text: str, *, channel: str) -> list[Fact]:
        out: list[Fact] = []
        for raw in _sentences(text):
            s = _FILLER.sub("", raw).strip()
            if not s or _GREETING.match(s):
                continue
            fact_type: FactType = "event"
            if _INTENT_CUES.search(s):
                fact_type = "intent"
            elif _ISSUE_CUES.search(s):
                fact_type = "issue"
            elif _RESOLUTION_CUES.search(s):
                fact_type = "resolution"
            elif _PROFILE_CUES.search(s):
                fact_type = "profile"

            entities: list[str] = []
            for m in _ENTITY_ORDER.finditer(s):
                entities.append(f"order_{m.group(1)}")
            for m in _ENTITY_MONEY.finditer(s):
                entities.append(f"money_{m.group(0)}")

            confidence = 0.7 + (0.1 if entities else 0.0) + (0.1 if fact_type != "event" else 0.0)
            out.append(Fact(
                fact=_collapse_ws(s),
                type=fact_type,
                entities=entities,
                confidence=min(confidence, 0.95),
            ))
        return out


class LLMExtractor(Extractor):
    """Structured extraction via an LLM. JSON mode expected."""

    def __init__(self, config: MemnexConfig) -> None:
        self._cfg = config
        self._client = self._build_client(config)

    def _build_client(self, cfg: MemnexConfig):
        if cfg.llm_provider == "openai":
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError("`pip install memnex[llm-openai]`.") from e
            return AsyncOpenAI(api_key=cfg.llm_api_key)
        if cfg.llm_provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:
                raise ImportError("`pip install memnex[llm-anthropic]`.") from e
            return AsyncAnthropic(api_key=cfg.llm_api_key)
        if cfg.llm_provider == "ollama":
            # Use OpenAI-compat client against local Ollama.
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError("`pip install memnex[llm-openai]`.") from e
            return AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        raise ValueError(f"Unsupported LLM provider: {cfg.llm_provider}")

    _PROMPT = (
        "Extract structured facts from this conversation. Return JSON: "
        '{"facts":[{"fact": str, "type": "event|intent|profile|preference|issue|resolution", '
        '"entities": [str], "confidence": float}]}. '
        "Drop greetings, filler words, repetitions. Only include information-bearing facts."
    )

    async def extract(self, text: str, *, channel: str) -> list[Fact]:
        if self._cfg.llm_provider == "anthropic":
            resp = await self._client.messages.create(  # type: ignore[union-attr]
                model=self._cfg.llm_model,
                max_tokens=1024,
                system=self._PROMPT,
                messages=[{"role": "user", "content": f"Channel: {channel}\n\n{text}"}],
            )
            content = resp.content[0].text  # type: ignore[attr-defined]
        else:
            resp = await self._client.chat.completions.create(  # type: ignore[union-attr]
                model=self._cfg.llm_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._PROMPT},
                    {"role": "user", "content": f"Channel: {channel}\n\n{text}"},
                ],
            )
            content = resp.choices[0].message.content
        try:
            data = json.loads(_strip_json_fence(content))
            return [Fact.model_validate(f) for f in data.get("facts", [])]
        except Exception:
            # Fall back to rule-based if parsing fails.
            return await RuleBasedExtractor().extract(text, channel=channel)


def build_extractor(config: MemnexConfig) -> Extractor:
    # Hybrid extractor (rules + fuzzy + optional encoder) is the new default.
    # LLM extractor is still available by setting llm_provider != "none".
    if config.llm_provider == "none":
        from memnex.memory.hybrid_extractor import HybridConfig, HybridExtractor
        return HybridExtractor(HybridConfig(use_encoder=False))
    return LLMExtractor(config)


# --- helpers ------------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"(?<=[\.\!\?])\s+")
_WS = re.compile(r"\s+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]


def _collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip().lstrip(",.;: ").strip()


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return content.strip()
