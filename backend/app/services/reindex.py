"""
Re-embed a document's existing chunks, used by POST /api/reindex.

Used after switching embedding providers: chunk text in Postgres is the system
of record, so we delete the document's Qdrant points and re-embed/upsert from
the stored chunks, with no re-upload or re-parse. Runs as a background task
with the same status mirroring as initial ingestion.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.db.vector_store import get_vector_store
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.providers.factory import get_embedder
from app.services.ingestion import set_live_status

logger = get_logger(__name__)

_EMBED_BATCH = 64
_PREVIEW_CHARS = 200


async def reindex_document(document_id: UUID) -> None:
    """Delete + rebuild the vectors for one document from its stored chunks."""
    async with AsyncSessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        try:
            document.status = DocumentStatus.processing
            await session.commit()
            await set_live_status(document_id, "processing")

            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            )
            chunks = list(result.scalars().all())
            if not chunks:
                raise ValueError("Document has no chunks to reindex.")

            # Snapshot what we need, then release the transaction: everything
            # below is slow model/network work and must not hold the database.
            user_id, doc_id = str(document.user_id), str(document.id)
            points = [
                {
                    "id": str(chunk.qdrant_point_id),
                    "chunk_id": str(chunk.id),
                    "content": chunk.content,
                    "page_number": chunk.page_number,
                }
                for chunk in chunks
            ]
            await session.commit()

            await get_vector_store().delete_by_document(document_id)

            embedder = get_embedder()
            for i in range(0, len(points), _EMBED_BATCH):
                batch = points[i : i + _EMBED_BATCH]
                vectors = await embedder.embed([p["content"] for p in batch])
                await get_vector_store().upsert(
                    [
                        {
                            "id": p["id"],
                            "vector": vector,
                            "payload": {
                                "user_id": user_id,
                                "document_id": doc_id,
                                "chunk_id": p["chunk_id"],
                                "page_number": p["page_number"],
                                "content_preview": p["content"][:_PREVIEW_CHARS],
                            },
                        }
                        for p, vector in zip(batch, vectors, strict=True)
                    ]
                )

            document.status = DocumentStatus.ready
            document.error_reason = None
            await session.commit()
            await set_live_status(document_id, "ready")
            logger.info(
                "document reindexed",
                extra={"document_id": str(document_id), "chunks": len(chunks)},
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            document = await session.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.failed
                document.error_reason = f"Reindex failed: {exc}"[:2000]
                await session.commit()
            await set_live_status(document_id, "failed")
            logger.error("reindex failed", extra={"document_id": str(document_id)}, exc_info=exc)
