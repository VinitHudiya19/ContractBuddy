"""
Shared async Redis client.

A single connection pool is created lazily and reused across the app. Redis
backs four concerns from the spec: sliding-window rate limits, the JWT logout
blacklist, live document-processing status, and metrics counters.
"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the process-wide Redis client (created on first call)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
