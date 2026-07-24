"""
Admin endpoints for user management and simple counts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.enums import MessageRole
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.admin import (
    AdminUserRow,
    AdminUserUpdate,
    UsageStats,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

_DAYS = 14


def _day_range() -> list[str]:
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(_DAYS - 1, -1, -1)]


@router.get("/users", response_model=list[AdminUserRow])
async def list_users(
    search: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserRow]:
    repo = UserRepository(db)
    users = await repo.list_all(search=search)

    # Total documents uploaded by each user
    doc_counts = dict(
        (await db.execute(
            select(Document.user_id, func.count(Document.id)).group_by(Document.user_id)
        )).all()
    )
    # Total questions asked by each user
    query_counts = dict(
        (await db.execute(
            select(Conversation.user_id, func.count(Message.id))
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.role == MessageRole.user)
            .group_by(Conversation.user_id)
        )).all()
    )

    rows = []
    for user in users:
        row = AdminUserRow.model_validate(user)
        row.document_count = int(doc_counts.get(user.id, 0))
        row.query_count = int(query_counts.get(user.id, 0))
        rows.append(row)
    return rows


@router.patch("/users/{user_id}", response_model=AdminUserRow)
async def update_user(
    user_id: UUID,
    body: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserRow:
    if user_id == admin.id and not body.is_active:
        raise ValidationError("You cannot deactivate your own admin account.")
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")
    await repo.set_active(user, body.is_active)
    await db.commit()
    return AdminUserRow.model_validate(user)


@router.get("/stats", response_model=UsageStats)
async def usage_stats(db: AsyncSession = Depends(get_db)) -> UsageStats:
    async def _count(entity) -> int:
        return int((await db.execute(select(func.count()).select_from(entity))).scalar_one())

    days = _day_range()
    cutoff = datetime.now(timezone.utc) - timedelta(days=_DAYS)

    # Get queries and uploads counts by day
    queries_rows = (await db.execute(
        select(func.date(Message.created_at), func.count(Message.id))
        .where(Message.role == MessageRole.user, Message.created_at >= cutoff)
        .group_by(func.date(Message.created_at))
    )).all()
    uploads_rows = (await db.execute(
        select(func.date(Document.uploaded_at), func.count(Document.id))
        .where(Document.uploaded_at >= cutoff)
        .group_by(func.date(Document.uploaded_at))
    )).all()
    queries_by_day = {str(d): int(c) for d, c in queries_rows}
    uploads_by_day = {str(d): int(c) for d, c in uploads_rows}

    return UsageStats(
        total_users=await _count(User),
        total_documents=await _count(Document),
        total_conversations=await _count(Conversation),
        total_messages=await _count(Message),
        queries_per_day=[{"date": d, "count": queries_by_day.get(d, 0)} for d in days],
        uploads_per_day=[{"date": d, "count": uploads_by_day.get(d, 0)} for d in days],
    )
