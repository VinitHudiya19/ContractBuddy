"""
Per-user sliding-window rate limiting, backed by Redis.

Implemented as a sorted set of request timestamps per (user, endpoint): we drop
entries older than the window, count what remains, and reject if over the limit.
This is a true sliding window (not a fixed bucket), so bursts at window edges
don't slip through. Used as a FastAPI dependency on expensive endpoints.
"""
import time

from fastapi import Depends, Request

from app.core.config import settings
from app.core.exceptions import RateLimitExceededError
from app.core.logging import get_logger
from app.db.redis_client import get_redis
from app.dependencies.auth import get_current_user
from app.models.user import User

logger = get_logger(__name__)


class RateLimiter:
    def __init__(self, *, requests: int | None = None, window_seconds: int | None = None):
        self.requests = requests or settings.rate_limit_requests
        self.window = window_seconds or settings.rate_limit_window_seconds

    async def __call__(
        self, request: Request, user: User = Depends(get_current_user)
    ) -> None:
        route = request.scope.get("route")
        endpoint = route.path if route else request.url.path
        key = f"rate_limit:{user.id}:{endpoint}"
        now = time.time()

        try:
            redis = get_redis()
            # Atomic: prune old, add current, count, set TTL.
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - self.window)
            pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
            pipe.zcard(key)
            pipe.expire(key, self.window)
            _, _, count, _ = await pipe.execute()
        except Exception as exc:
            # Redis is optional infrastructure. Fail *open* so a missing cache
            # never blocks legitimate traffic, but log it. Silently dropping
            # rate limiting is exactly the kind of thing that goes unnoticed.
            logger.warning(
                "rate limiting disabled for this request (redis unavailable)",
                extra={"endpoint": endpoint, "error": f"{type(exc).__name__}: {exc}"},
            )
            return

        if count > self.requests:
            raise RateLimitExceededError(
                f"Rate limit exceeded: max {self.requests} requests per "
                f"{self.window}s. Retry in ~{self.window}s."
            )


# Default limiter using configured global values.
rate_limit = RateLimiter()
# Tighter limiter for heavy AI endpoints (ask / summarize).
ai_rate_limit = RateLimiter(requests=max(10, settings.rate_limit_requests // 3))
