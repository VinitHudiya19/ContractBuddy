"""
Document ingestion. Runs in a background task after the upload responds.

parse -> chunk -> save chunk rows -> embed -> store vectors

The document status goes processing -> ready, or failed with a reason. It is
also written to Redis so the frontend can poll status without hitting the
database every time. If any stage throws, the document is marked failed instead
of being left stuck on processing forever. A crash takes the task down before it
can do that, so `services.recovery` clears the leftovers on the next startup.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.db.redis_client import get_redis
from app.db.session import AsyncSessionLocal
from app.db.vector_store import get_vector_store
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.providers.factory import get_embedder
from app.services.chunking import chunk_pages
from app.services.parsing import parse_document

logger = get_logger(__name__)

_EMBED_BATCH = 64
_PREVIEW_CHARS = 200


async def set_live_status(document_id: UUID, status: str) -> None:
    """Mirror processing status into Redis for cheap polling (1h TTL)."""
    try:
        await get_redis().setex(f"doc_status:{document_id}", 3600, status)
    except Exception as exc:  # noqa: BLE001 (status cache is best-effort)
        logger.warning("doc status mirror failed", extra={"error": str(exc)})


async def ingest_document(document_id: UUID, file_path: str) -> None:
    """
    Full ingestion for one document. Opens its own DB session because it runs
    outside the request lifecycle (BackgroundTasks).
    """
    async with AsyncSessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            logger.error("ingest: document vanished", extra={"document_id": str(document_id)})
            return

        try:
            await set_live_status(document_id, "processing")

            # 1. Parse → page-level text.
            pages, page_count = parse_document(Path(file_path), document.file_type)
            if not pages:
                raise ValueError("No extractable text found in the document.")

            # 2. Chunk (~500 tokens, 50 overlap), page-aware.
            chunks = chunk_pages(pages)
            if not chunks:
                raise ValueError("Document produced no usable chunks.")

            # 3. Persist chunk rows. content_tsv (the lexical leg) is a
            #    generated column on Postgres, so it populates itself from
            #    `content`. Commit immediately: embedding below is slow network
            #    /CPU work, and holding a write transaction open across it locks
            #    the database for every concurrent request (SQLite especially).
            chunk_rows: list[DocumentChunk] = []
            for c in chunks:
                row = DocumentChunk(
                    document_id=document.id,
                    user_id=document.user_id,
                    chunk_index=c.index,
                    content=c.content,
                    token_count=c.token_count,
                    page_number=c.page_number,
                )
                session.add(row)
                chunk_rows.append(row)
            await session.commit()

            # 4. Embed in batches + 5. upsert vectors with tenant payload.
            #    Snapshot the fields we need so no lazy load re-opens a
            #    transaction while we are talking to the model and to Qdrant.
            points = [
                {
                    "id": str(row.qdrant_point_id),
                    "chunk_id": str(row.id),
                    "content": row.content,
                    "page_number": row.page_number,
                }
                for row in chunk_rows
            ]
            user_id, doc_id = str(document.user_id), str(document.id)

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
            document.page_count = page_count
            document.chunk_count = len(chunk_rows)
            document.error_reason = None
            await session.commit()
            await set_live_status(document_id, "ready")
            logger.info(
                "document ingested",
                extra={"document_id": str(document_id), "chunks": len(chunk_rows)},
            )

        except Exception as exc:  # noqa: BLE001 (any failure means failed status)
            await session.rollback()
            # Re-fetch on the fresh transaction so the status update sticks.
            document = await session.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.failed
                document.error_reason = str(exc)[:2000]
                await session.commit()
            await set_live_status(document_id, "failed")
            logger.error(
                "document ingestion failed",
                extra={"document_id": str(document_id)},
                exc_info=exc,
            )
        finally:
            # The chunks are the system of record, so the raw file is not kept.
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass


def upload_dir() -> Path:
    """Staging directory for in-flight uploads (absolute, created on demand)."""
    path = settings.upload_path
    path.mkdir(parents=True, exist_ok=True)
    return path
