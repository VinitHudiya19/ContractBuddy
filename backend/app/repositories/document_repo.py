"""
Database repository for Documents and Chunks.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus, FileType


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def get_owned(self, document_id: UUID, user_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document).where(Document.user_id == user_id).order_by(Document.uploaded_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: UUID,
        filename: str,
        file_type: FileType,
        file_size_bytes: int,
    ) -> Document:
        document = Document(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            status=DocumentStatus.processing,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def delete(self, document: Document) -> None:
        await self.session.delete(document)
        await self.session.flush()

    async def chunks_for_document(self, document_id: UUID) -> list[DocumentChunk]:
        result = await self.session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())
