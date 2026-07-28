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
from app.db.redis_client import get_redis
from app.dependencies.auth import get_current_user
from app.models.user import User


class RateLimiter:
    def __init__(self, *, requests: int | None = None, window_seconds: int | None = None):
        self.requests = requests or settings.rate_limit_requests
        self.window = window_seconds or settings.rate_limit_window_seconds

    async def __call__(
        self, request: Request, user: User = Depends(get_current_user)
    ) -> None:
        try:
            redis = get_redis()
            endpoint = request.scope.get("route").path if request.scope.get("route") else request.url.path
            key = f"rate_limit:{user.id}:{endpoint}"
            now = time.time()
            window_start = now - self.window

            # Atomic: prune old, add current, count, set TTL.
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
            pipe.zcard(key)
            pipe.expire(key, self.window)
            _, _, count, _ = await pipe.execute()

            if count > self.requests:
                # Roughly how long until the oldest in-window request ages out.
                retry_after = self.window
                raise RateLimitExceededError(
                    f"Rate limit exceeded: max {self.requests} requests per "
                    f"{self.window}s. Retry in ~{retry_after}s."
                )
        except RateLimitExceededError:
            raise
        except Exception:
            pass


# Default limiter using configured global values.
rate_limit = RateLimiter()
# Tighter limiter for heavy AI endpoints (ask / summarize).
ai_rate_limit = RateLimiter(requests=max(10, settings.rate_limit_requests // 3))
