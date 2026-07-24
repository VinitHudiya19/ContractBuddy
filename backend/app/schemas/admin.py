"""
Pydantic schemas for admin endpoints.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import UserRole


class AdminUserRow(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    document_count: int = 0
    query_count: int = 0

    model_config = {"from_attributes": True}


class AdminUserUpdate(BaseModel):
    is_active: bool


class UsageStats(BaseModel):
    total_users: int
    total_documents: int
    total_conversations: int
    total_messages: int
    queries_per_day: list[dict]
    uploads_per_day: list[dict]
