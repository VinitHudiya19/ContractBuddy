"""
User profile endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import ProfileUpdate, UserPublic

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/me", response_model=UserPublic)
async def get_me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user)


@router.patch("/profile", response_model=UserPublic)
async def update_profile(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPublic:
    if body.full_name is not None:
        user.full_name = body.full_name
    await db.commit()
    await db.refresh(user)
    return UserPublic.model_validate(user)
