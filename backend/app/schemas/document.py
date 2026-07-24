"""
Pydantic schemas for documents.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import DocumentStatus, FileType


class DocumentPublic(BaseModel):
    id: UUID
    filename: str
    file_type: FileType
    file_size_bytes: int
    status: DocumentStatus
    page_count: int | None
    chunk_count: int
    error_reason: str | None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    id: UUID
    status: DocumentStatus
    error_reason: str | None = None


class SummarizeRequest(BaseModel):
    extra_document_ids: list[UUID] = Field(default_factory=list, max_length=10)


class SummarizeResponse(BaseModel):
    summary: str
    stats: dict


class ReindexRequest(BaseModel):
    document_id: UUID


class ReindexResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus
