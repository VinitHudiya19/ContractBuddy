"""
Simple helper functions to get our LLM (Groq Llama-3) and Embedding (Local Sentence-Transformers) clients.
We use lru_cache so we don't reload or re-initialize model objects on every single API request.
"""
from __future__ import annotations

from functools import lru_cache

from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.local_embed import LocalEmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.groq_provider import GroqProvider


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    # returns single instance of groq llm provider
    return GroqProvider()


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingProvider:
    # returns single instance of our local sentence-transformer embedding provider
    return LocalEmbeddingProvider()
