"""
Startup chores: warm the local models.

Safe to fail: the app still boots if warmup does not finish.
"""
from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.factory import get_embedder

logger = get_logger(__name__)


async def warm_models() -> None:
    """
    Load the embedding and reranking models ahead of the first request.

    They are lazily loaded singletons, so without this the very first question a
    user asks pays the full model load (and, on a cold machine, the download).
    Runs detached from startup so the API begins serving immediately.
    """
    started = time.perf_counter()
    try:
        await get_embedder().embed_one("warmup")

        if settings.rerank_enabled:
            from sentence_transformers import CrossEncoder

            from app.services import hybrid_retrieval

            if hybrid_retrieval._reranker is None:
                hybrid_retrieval._reranker = await asyncio.to_thread(
                    CrossEncoder, settings.reranker_model, device="cpu"
                )

        logger.info(
            "models warm", extra={"seconds": round(time.perf_counter() - started, 1)}
        )
    except Exception as exc:
        # First question will just be slower; nothing is broken.
        logger.warning(
            "model warmup failed", extra={"error": f"{type(exc).__name__}: {exc}"}
        )
