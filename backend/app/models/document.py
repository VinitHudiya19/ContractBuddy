"""
ORM models for Documents and Chunks.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import DocumentStatus, FileType
from app.models.types import GUID, new_uuid


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    user_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[FileType] = mapped_column(Enum(FileType, name="file_type"), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.processing,
        nullable=False,
        index=True,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="documents")  # noqa: F821
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[GUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    document_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[GUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qdrant_point_id: Mapped[GUID] = mapped_column(GUID(), nullable=False, default=new_uuid)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ChunkVector(Base):
    """
    Embeddings for the built-in SQL vector store (used when Qdrant is not
    running). The Qdrant backend never touches this table.

    Vectors are stored as raw little-endian float32 so a whole result set can be
    read into one NumPy matrix with a single `frombuffer` call.
    """

    __tablename__ = "chunk_vectors"

    point_id: Mapped[GUID] = mapped_column(GUID(), primary_key=True)
    chunk_id: Mapped[GUID] = mapped_column(GUID(), index=True, nullable=False)
    user_id: Mapped[GUID] = mapped_column(GUID(), index=True, nullable=False)
    document_id: Mapped[GUID] = mapped_column(GUID(), index=True, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_preview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
