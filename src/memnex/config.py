"""Configuration for Memnex.

MemnexConfig is a plain Pydantic model — no global state, no hidden magic.
Pass it to ``Memnex(config=...)`` or use the top-level kwargs in ``Memnex(...)``.
"""
from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

ConflictStrategy = Literal["latest_wins", "keep_both", "ask_agent"]
PIIMaskStrategy = Literal["hash", "redact", "encrypt"]
LLMProvider = Literal["openai", "anthropic", "google", "sarvam", "ollama", "none"]
EmbeddingProvider = Literal["google", "openai", "hash"]


class MemnexConfig(BaseModel):
    """Runtime configuration for a Memnex instance."""

    tenant_id: str = Field(..., description="Tenant to scope all operations to.")

    # Storage URLs. When None, the in-memory backend is used (good for tests + local demos).
    postgres_url: str | None = None
    redis_url: str | None = None
    qdrant_url: str | None = None

    # Fact extraction LLM (independent of embeddings).
    llm_provider: LLMProvider = "none"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None

    # Embeddings. Default: Google Generative AI via LangChain.
    # Set GOOGLE_API_KEY in the environment or pass google_api_key here.
    embedding_provider: EmbeddingProvider = "google"
    embedding_model: str = "models/text-embedding-004"
    embedding_dimensions: int = 768
    google_api_key: str | None = None

    # Behaviour.
    conflict_strategy: ConflictStrategy = "latest_wins"
    pii_detection: bool = True
    # Regulated identifiers only. We deliberately do NOT mask names, addresses,
    # order IDs, or preferences — the memory product exists to remember those.
    pii_fields_to_mask: list[str] = Field(
        default_factory=lambda: [
            "aadhaar", "pan", "credit_card", "bank_account",
            "iban", "ssn", "email", "phone", "otp",
        ]
    )
    pii_mask_strategy: PIIMaskStrategy = "hash"
    # Optional second layer. Requires `pip install memnex[privacy-presidio]`.
    # Even when enabled, only regulated entities are masked (see pii_detector).
    pii_use_presidio: bool = False

    # Tuning.
    redis_cache_ttl_hours: int = 24
    max_facts_per_write: int = 50
    default_token_budget: int = 2000
    salience_drop_threshold: float = 0.1
    conflict_similarity_threshold: float = 0.85
    fuzzy_match_window_hours: int = 24

    # Observability.
    enable_metrics: bool = True
    log_level: str = "INFO"

    # Provenance + trust policy (see memnex.provenance.policy.TrustPolicy).
    # None = use defaults. Dict form is accepted for ease of env-based config.
    trust_policy: dict[str, Any] | None = None

    model_config = {"frozen": True}

    @classmethod
    def from_env(cls, tenant_id: str | None = None) -> "MemnexConfig":
        """Build config from MEMNEX_* environment variables."""
        tid = tenant_id or os.getenv("MEMNEX_TENANT_ID")
        if not tid:
            raise ValueError("MEMNEX_TENANT_ID must be set or tenant_id passed explicitly")
        kwargs: dict[str, Any] = dict(
            tenant_id=tid,
            postgres_url=os.getenv("MEMNEX_POSTGRES_URL"),
            redis_url=os.getenv("MEMNEX_REDIS_URL"),
            qdrant_url=os.getenv("MEMNEX_QDRANT_URL"),
            llm_provider=os.getenv("MEMNEX_LLM_PROVIDER", "none"),
            llm_model=os.getenv("MEMNEX_LLM_MODEL", "gpt-4o-mini"),
            llm_api_key=os.getenv("MEMNEX_LLM_API_KEY"),
            embedding_provider=os.getenv("MEMNEX_EMBEDDING_PROVIDER", "google"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            pii_use_presidio=os.getenv("MEMNEX_PII_USE_PRESIDIO", "").lower() in ("1", "true", "yes"),
            log_level=os.getenv("MEMNEX_LOG_LEVEL", "INFO"),
        )
        if em := os.getenv("MEMNEX_EMBEDDING_MODEL"):
            kwargs["embedding_model"] = em
        if ed := os.getenv("MEMNEX_EMBEDDING_DIMENSIONS"):
            kwargs["embedding_dimensions"] = int(ed)
        return cls(**kwargs)
