"""
Base interface for text embeddings.
Our default implementation uses local sentence-transformers (384-dim vectors).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # converts list of string inputs to vector lists
        pass

    async def embed_one(self, text: str) -> list[float]:
        # helper to embed a single string
        vectors = await self.embed([text])
        return vectors[0]
