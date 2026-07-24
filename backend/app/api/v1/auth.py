"""
Auth endpoints: register, login, refresh (with rotation), logout (blacklist).

Refresh-token rotation: every successful /refresh revokes the presented token
and issues a brand-new one. A replayed (already-rotated) token is rejected —
basic reuse detection. Logout blacklists the access token's `jti` in Redis until
its natural expiry and revokes the user's refresh tokens.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    InactiveUserError,
    InvalidTokenError,
    UserAlreadyExistsError,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    refresh_token_expiry,
    verify_password,
)
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


async def _issue_tokens(repo: UserRepository, user: User) -> TokenResponse:
    access, _jti, expires_at = create_access_token(user_id=str(user.id), role=user.role.value)
    refresh = generate_refresh_token()
    await repo.store_refresh_token(
        user_id=user.id, raw_token=refresh, expires_at=refresh_token_expiry()
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=UserPublic, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserPublic:
    repo = UserRepository(db)
    if await repo.get_by_email(body.email):
        raise UserAlreadyExistsError()
    user = await repo.create(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    await db.commit()
    return UserPublic.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    repo = UserRepository(db)
    user = await repo.get_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password.")
    if not user.is_active:
        raise InactiveUserError()
    tokens = await _issue_tokens(repo, user)
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    repo = UserRepository(db)
    rt = await repo.get_refresh_token(body.refresh_token)
    if rt is None or not repo.is_refresh_token_valid(rt):
        # Token unknown, expired, or already rotated → reject.
        raise InvalidTokenError("Refresh token is invalid or expired.")

    user = await repo.get_by_id(rt.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("Account is unavailable.")

    # Rotate: revoke the presented token, issue a fresh pair.
    await repo.revoke_refresh_token(rt)
    tokens = await _issue_tokens(repo, user)
    await db.commit()
    return tokens


@router.post("/logout", status_code=204, response_model=None)
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Blacklist this access token's jti until it would expire anyway.
    if credentials and credentials.credentials:
        payload = decode_access_token(credentials.credentials)
        jti = payload.get("jti")
        exp = payload.get("exp", 0)
        ttl = max(1, int(exp - time.time()))
        if jti:
            await get_redis().setex(f"token_blacklist:{jti}", ttl, "1")

    # Revoke refresh tokens so they can't mint new access tokens.
    repo = UserRepository(db)
    await repo.revoke_all_for_user(user.id)
    await db.commit()
