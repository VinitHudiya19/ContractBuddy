"""
Auth dependencies.

`get_current_user` validates the bearer access token, checks the Redis logout
blacklist (by `jti`), loads the user, and confirms the account is active.

There are no roles. Every account is the same, and access is decided by
ownership: the repositories scope every query to `user_id`.
"""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InactiveUserError,
    InvalidTokenError,
)
from app.core.security import decode_access_token
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repo import UserRepository

# auto_error=False so we can raise our own uniform error envelope.
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise InvalidTokenError("Missing bearer token.")

    payload = decode_access_token(credentials.credentials)
    jti = payload.get("jti")

    # Reject tokens explicitly blacklisted at logout.
    try:
        redis = get_redis()
        if jti and await redis.exists(f"token_blacklist:{jti}"):
            raise InvalidTokenError("Token has been revoked.")
    except InvalidTokenError:
        raise
    except Exception:
        pass

    user_id = payload["sub"]
    repo = UserRepository(db)
    from uuid import UUID

    user = await repo.get_by_id(UUID(user_id))
    if user is None:
        raise InvalidTokenError("User no longer exists.")
    if not user.is_active:
        raise InactiveUserError()

    # Stash for telemetry/logging middleware.
    request.state.user_id = str(user.id)
    request.state.jti = jti
    return user

