"""
User + refresh-token data access.

Repositories isolate DB access from business logic (services/routers) so the
query surface is small and testable. Nothing here commits; the
caller owns the transaction boundary.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_refresh_token
from app.models.user import RefreshToken, User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---- users ----
    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(func.lower(User.email) == email.lower())
        )
        return result.scalar_one_or_none()

    async def create(
        self, *, email: str, hashed_password: str, full_name: str
    ) -> User:
        user = User(
            email=email.lower(),
            hashed_password=hashed_password,
            full_name=full_name,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_all(self, *, search: str | None = None, limit: int = 100, offset: int = 0):
        stmt = select(User).order_by(User.created_at.desc())
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(User.email).like(like) | func.lower(User.full_name).like(like)
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_active(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        await self.session.flush()
        return user

    # ---- refresh tokens ----
    async def store_refresh_token(
        self, *, user_id: UUID, raw_token: str, expires_at: datetime
    ) -> RefreshToken:
        rt = RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=expires_at,
        )
        self.session.add(rt)
        await self.session.flush()
        return rt

    async def get_refresh_token(self, raw_token: str) -> RefreshToken | None:
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, rt: RefreshToken) -> None:
        rt.revoked = True
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
            )
        )
        for rt in result.scalars().all():
            rt.revoked = True
        await self.session.flush()

    @staticmethod
    def is_refresh_token_valid(rt: RefreshToken) -> bool:
        if rt.revoked:
            return False
        expires = rt.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires > datetime.now(UTC)
