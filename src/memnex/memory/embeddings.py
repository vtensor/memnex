"""Embedding providers.

Default: Google Generative AI embeddings via LangChain. Set ``GOOGLE_API_KEY``
in the environment (or pass ``google_api_key`` on ``MemnexConfig``).

Alternates:
- OpenAI ``text-embedding-3-small`` / ``-large`` (``embedding_provider="openai"``).
- HashEmbedder: deterministic, zero-dependency. Intended for tests only. If the
  configured provider fails to initialize (missing key or missing dep), we fall
  back to HashEmbedder with a loud warning so tests keep working and production
  misconfigurations are visible.
"""
from __future__ import annotations

import hashlib
import logging
import os
from abc import ABC, abstractmethod

from memnex.config import MemnexConfig

logger = logging.getLogger(__name__)


class Embedder(ABC):
    dim: int

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...


class HashEmbedder(Embedder):
    """Deterministic, low-quality. Tests / fallback only — never a real default."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in text.lower().split():
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            vec[h % self.dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class GoogleEmbedder(Embedder):
    """Google Generative AI embeddings, invoked through LangChain."""

    def __init__(self, config: MemnexConfig) -> None:
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as e:
            raise ImportError(
                "Google embeddings require `pip install memnex[embeddings-google]` "
                "(langchain-google-genai)."
            ) from e
        api_key = config.google_api_key or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY is not set. Provide it in the environment or on "
                "MemnexConfig.google_api_key."
            )
        self._client = GoogleGenerativeAIEmbeddings(
            model=config.embedding_model,
            google_api_key=api_key,
        )
        self.dim = config.embedding_dimensions

    async def embed(self, text: str) -> list[float]:
        import anyio

        # LangChain's embed_query is sync; push to a worker thread.
        return await anyio.to_thread.run_sync(self._client.embed_query, text)


class OpenAIEmbedder(Embedder):
    def __init__(self, config: MemnexConfig) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError("`pip install memnex[llm-openai]`.") from e
        if not config.llm_api_key:
            raise ValueError("llm_api_key is required for OpenAI embeddings.")
        self._client = AsyncOpenAI(api_key=config.llm_api_key)
        self._model = config.embedding_model
        self.dim = config.embedding_dimensions

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(
            model=self._model, input=text, dimensions=self.dim
        )
        return list(resp.data[0].embedding)


def build_embedder(config: MemnexConfig) -> Embedder:
    provider = config.embedding_provider
    if provider == "google":
        try:
            return GoogleEmbedder(config)
        except (ImportError, ValueError) as e:
            logger.warning(
                "Google embedder unavailable (%s). Falling back to HashEmbedder — "
                "retrieval quality will be near-random. Set GOOGLE_API_KEY and "
                "install memnex[embeddings-google] for production use.",
                e,
            )
            return HashEmbedder(config.embedding_dimensions)
    if provider == "openai":
        return OpenAIEmbedder(config)
    if provider == "hash":
        return HashEmbedder(config.embedding_dimensions)
    raise ValueError(f"Unknown embedding_provider: {provider!r}")
