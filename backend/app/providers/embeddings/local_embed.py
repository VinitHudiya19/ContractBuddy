"""
Local sentence-transformers embedding helper.
Loads the model lazily on first use and runs encoding in a background thread so we don't block asyncio event loop.
"""
from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.exceptions import EmbeddingProviderError
from app.providers.embeddings.base import EmbeddingProvider

_model = None  # process-wide singleton


def _load_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingProviderError("sentence-transformers is not installed.") from exc
        _model = SentenceTransformer(settings.local_embed_model)
    return _model


class LocalEmbeddingProvider(EmbeddingProvider):
    name = "local"

    def __init__(self) -> None:
        self.dim = settings.embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = _load_model()
            vectors = model.encode(
                texts, normalize_embeddings=True, convert_to_numpy=True
            )
            return vectors.tolist()

        try:
            return await asyncio.to_thread(_encode)
        except Exception as exc:
            raise EmbeddingProviderError(f"Local embedding failed: {exc}") from exc
