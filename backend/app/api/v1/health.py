"""
Liveness check endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import qdrant_client
from app.db.redis_client import get_redis
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        postgres_ok = False

    try:
        redis_ok = bool(await get_redis().ping())
    except Exception:
        redis_ok = False

    qdrant_ok = await qdrant_client.health_check()

    return {
        "status": "ok" if (postgres_ok and redis_ok and qdrant_ok) else "degraded",
        "dependencies": {
            "postgres": postgres_ok,
            "redis": redis_ok,
            "qdrant": qdrant_ok,
        },
        "providers": {
            "llm": settings.llm_provider,
            "embeddings": settings.embedding_provider,
        },
    }
