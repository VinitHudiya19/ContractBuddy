"""
Pydantic schemas for conversations and messages.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import MessageRole


class ConversationCreate(BaseModel):
    document_scope: list[UUID] | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=200)


class ConversationPublic(BaseModel):
    id: UUID
    title: str
    document_scope: list[UUID] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CitationPublic(BaseModel):
    marker: str
    document_id: str
    filename: str
    page: int | None
    snippet: str


class MessagePublic(BaseModel):
    id: UUID
    role: MessageRole
    content: str
    citations: list[dict] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    stream: bool = True


class AskResponse(BaseModel):
    message: MessagePublic
