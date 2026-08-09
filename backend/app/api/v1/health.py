"""
Health endpoint.

Distinguishes *required* dependencies (the database and the active vector store)
from *optional* ones (Redis). Reporting "degraded" because an optional service
is absent would make a perfectly functional local install look broken, so
optional services are reported but do not by themselves fail the check.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.db.vector_store import get_vector_store

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    try:
        redis_ok = bool(await get_redis().ping())
    except Exception:
        redis_ok = False

    store = get_vector_store()
    vector_ok = await store.health_check()

    return {
        "status": "ok" if (database_ok and vector_ok) else "degraded",
        "dependencies": {
            "database": {
                "ok": database_ok,
                "engine": "sqlite" if settings.is_sqlite else "postgresql",
                "required": True,
            },
            "vector_store": {"ok": vector_ok, "backend": store.name, "required": True},
            # Rate limiting and cached document status degrade gracefully.
            "redis": {"ok": redis_ok, "required": False},
        },
        "providers": {
            "llm": settings.llm_provider,
            "embeddings": settings.embedding_provider,
        },
    }
