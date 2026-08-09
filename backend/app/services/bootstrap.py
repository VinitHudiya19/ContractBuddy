"""
Startup chores: seed the admin account and warm the local models.

Both are safe to fail — the app must still boot if either does.
"""
from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.enums import UserRole
from app.providers.factory import get_embedder
from app.repositories.user_repo import UserRepository

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


async def ensure_admin_user() -> None:
    try:
        async with AsyncSessionLocal() as session:
            repo = UserRepository(session)
            if await repo.get_by_email(settings.bootstrap_admin_email) is not None:
                return
            await repo.create(
                email=settings.bootstrap_admin_email,
                hashed_password=hash_password(settings.bootstrap_admin_password),
                full_name="Administrator",
                role=UserRole.admin,
            )
            await session.commit()
        logger.info(
            "bootstrap admin created", extra={"email": settings.bootstrap_admin_email}
        )
    except Exception as exc:
        # Never block startup on this — the app is usable without it and the
        # register endpoint still works.
        logger.warning(
            "bootstrap admin skipped", extra={"error": f"{type(exc).__name__}: {exc}"}
        )
