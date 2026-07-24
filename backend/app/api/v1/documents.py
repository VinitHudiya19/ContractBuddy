"""
Document upload, listing, deletion, and summarization endpoints.
"""
from __future__ import annotations

import re
import uuid as uuidlib
from uuid import UUID

import anyio
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    DocumentNotFoundError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.db import qdrant_client
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import ai_rate_limit, rate_limit
from app.models.enums import DocumentStatus, FileType
from app.models.user import User
from app.providers.factory import get_embedder
from app.repositories.document_repo import DocumentRepository
from app.schemas.document import (
    DocumentPublic,
    DocumentStatusResponse,
    ReindexRequest,
    ReindexResponse,
    SummarizeRequest,
    SummarizeResponse,
)
from app.services.ingestion import ingest_document, upload_dir
from app.services.reindex import reindex_document
from app.services.summarization import summarize_documents

router = APIRouter(prefix="/api/documents", tags=["documents"])

_ALLOWED = {
    "application/pdf": FileType.pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.docx,
}


@router.post("", response_model=DocumentPublic, status_code=201, dependencies=[Depends(rate_limit)])
async def upload_document(
    file: UploadFile,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentPublic:
    # Check mime type
    mime = file.content_type
    if mime not in _ALLOWED:
        raise UnsupportedFileTypeError("We only support PDF or DOCX files.")

    # Generate filename and path
    ext = ".pdf" if _ALLOWED[mime] is FileType.pdf else ".docx"
    file_id = uuidlib.uuid4()
    sys_name = f"{file_id}{ext}"
    path = upload_dir / sys_name

    # Write file to disk checking size limits
    size = 0
    async with await anyio.open_file(path, "wb") as f:
        while chunk := await file.read(65536):
            size += len(chunk)
            if size > settings.max_upload_size_bytes:
                # Remove file if too large
                await anyio.Path(path).unlink(missing_ok=True)
                raise FileTooLargeError("File exceeds 15MB upload limit.")
            await f.write(chunk)

    # Save metadata to database
    repo = DocumentRepository(db)
    document = await repo.create(
        user_id=user.id,
        filename=file.filename or "file",
        file_type=_ALLOWED[mime],
        file_size_bytes=size,
    )
    await db.commit()

    # Ingest document chunks in background
    background.add_task(ingest_document, document.id, path)
    return DocumentPublic.model_validate(document)


@router.get("", response_model=list[DocumentPublic])
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentPublic]:
    repo = DocumentRepository(db)
    return await repo.list_for_user(user.id)


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    repo = DocumentRepository(db)
    document = await repo.get_owned(document_id, user.id)
    if document is None:
        raise DocumentNotFoundError()

    # Check status from Redis mirror or DB
    redis = get_redis()
    status = await redis.get(f"doc:status:{document_id}")
    if status is not None:
        reason = await redis.get(f"doc:error:{document_id}")
        return DocumentStatusResponse(
            id=document_id,
            status=DocumentStatus(status),
            error_reason=reason,
        )

    return DocumentStatusResponse(
        id=document_id,
        status=document.status,
        error_reason=document.error_reason,
    )


@router.delete("/{document_id}", response_model=None, status_code=204)
async def delete_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = DocumentRepository(db)
    document = await repo.get_owned(document_id, user.id)
    if document is None:
        raise DocumentNotFoundError()
    await repo.delete(document)
    await qdrant_client.delete_by_document(document_id)
    await db.commit()


@router.post("/{document_id}/summarize", response_model=SummarizeResponse,
             dependencies=[Depends(ai_rate_limit)])
async def summarize(
    document_id: UUID,
    body: SummarizeRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SummarizeResponse:
    ids = [document_id] + list(body.extra_document_ids if body else [])
    summary, stats = await summarize_documents(db, user_id=user.id, document_ids=ids)
    return SummarizeResponse(summary=summary, stats=stats)


reindex_router = APIRouter(prefix="/api", tags=["documents"])


@reindex_router.post("/reindex", response_model=ReindexResponse,
                     dependencies=[Depends(rate_limit)])
async def reindex(
    body: ReindexRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReindexResponse:
    repo = DocumentRepository(db)
    document = await repo.get_owned(body.document_id, user.id)
    if document is None:
        raise DocumentNotFoundError()

    # Re-embed vectors in background
    document.status = DocumentStatus.processing
    await db.commit()
    background.add_task(reindex_document, document.id)
    return ReindexResponse(document_id=document.id, status=DocumentStatus.processing)
