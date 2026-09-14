"""
Provider wiring.

Business logic never imports a concrete provider. It asks for `get_llm()` or
`get_embedder()` and gets whatever `LLM_PROVIDER` / `EMBEDDING_PROVIDER` in the
environment selected. Instances are cached because loading a local model is
expensive and must not happen per request.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.local_embed import LocalEmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.extractive_provider import ExtractiveProvider
from app.providers.llm.groq_provider import GroqProvider

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    """
    Active LLM. Falls back to the extractive provider when no key is configured,
    so the app stays usable out of the box instead of failing on the first
    question, and it says so in the answer instead of faking generation.
    """
    if settings.groq_api_key:
        try:
            return GroqProvider()
        except Exception as exc:
            logger.error(
                "groq provider failed to initialise, using extractive fallback",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
    else:
        logger.warning("no GROQ_API_KEY set, answers will be extractive")
    return ExtractiveProvider()


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingProvider:
    """Active embedding provider (local sentence-transformers by default)."""
    return LocalEmbeddingProvider()
