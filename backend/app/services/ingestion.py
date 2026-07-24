"""
Document ingestion pipeline (§10.1).

Runs as a FastAPI BackgroundTask after upload returns 202:
    parse → clean/chunk → persist chunk rows (Postgres, content_tsv populates
    itself via the generated column) → embed → upsert vectors (Qdrant).

Status transitions: processing → ready | failed(error_reason). Live status is
mirrored to Redis (`doc_status:{id}`) so the frontend can poll cheaply without
hitting Postgres. Each stage is resilient: any failure marks the document
`failed` with a reason instead of leaving it stuck in `processing`.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.db import qdrant_client
from app.db.redis_client import get_redis
from app.db.session import AsyncSessionLocal
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
    except Exception as exc:  # noqa: BLE001 — status mirror is best-effort
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

            # 3. Persist chunk rows. content_tsv (BM25 leg) is a generated
            #    column on Postgres — it populates itself from `content`.
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
            await session.flush()

            # 4. Embed in batches + 5. upsert vectors with tenant payload.
            embedder = get_embedder()
            for i in range(0, len(chunk_rows), _EMBED_BATCH):
                batch = chunk_rows[i : i + _EMBED_BATCH]
                vectors = await embedder.embed([r.content for r in batch])
                await qdrant_client.upsert_chunks(
                    [
                        {
                            "id": str(row.qdrant_point_id),
                            "vector": vector,
                            "payload": {
                                "user_id": str(document.user_id),
                                "document_id": str(document.id),
                                "chunk_id": str(row.id),
                                "page_number": row.page_number,
                                "content_preview": row.content[:_PREVIEW_CHARS],
                            },
                        }
                        for row, vector in zip(batch, vectors)
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

        except Exception as exc:  # noqa: BLE001 — any failure = failed status
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
            # The original upload is not retained: chunks + vectors are the
            # system of record (privacy: no raw files at rest — §14).
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass


def upload_dir() -> Path:
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
