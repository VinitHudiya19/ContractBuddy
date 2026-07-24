"""
Re-embed a document's existing chunks (POST /api/reindex — §11).

Used after switching embedding providers: chunk text in Postgres is the system
of record, so we delete the document's Qdrant points and re-embed/upsert from
the stored chunks — no re-upload or re-parse needed. Runs as a background task
with the same status mirroring as initial ingestion.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.db import qdrant_client
from app.db.session import AsyncSessionLocal
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

            await qdrant_client.delete_by_document(document_id)

            embedder = get_embedder()
            for i in range(0, len(chunks), _EMBED_BATCH):
                batch = chunks[i : i + _EMBED_BATCH]
                vectors = await embedder.embed([c.content for c in batch])
                await qdrant_client.upsert_chunks(
                    [
                        {
                            "id": str(chunk.qdrant_point_id),
                            "vector": vector,
                            "payload": {
                                "user_id": str(document.user_id),
                                "document_id": str(document.id),
                                "chunk_id": str(chunk.id),
                                "page_number": chunk.page_number,
                                "content_preview": chunk.content[:_PREVIEW_CHARS],
                            },
                        }
                        for chunk, vector in zip(batch, vectors)
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
