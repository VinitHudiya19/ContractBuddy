"""
Qdrant access.

One collection (`document_chunks`). Every search carries a `user_id` payload
filter, plus the document ids when a conversation is scoped to specific files.
The filter is part of the search request, so Qdrant never scores another user's
vectors in the first place.

The client is created on first use and reused. Creating the collection is safe
to call every startup.
"""
from __future__ import annotations

from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30.0)
    return _client


async def close_qdrant() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def ensure_collection() -> None:
    """Create the collection if it doesn't exist (idempotent)."""
    client = get_qdrant()
    existing = await client.get_collections()
    names = {c.name for c in existing.collections}
    if settings.qdrant_collection in names:
        return
    await client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(
            size=settings.embedding_dim,
            distance=models.Distance.COSINE,
        ),
    )
    # Payload indexes make the user_id / document_id filters fast at scale.
    for field in ("user_id", "document_id"):
        try:
            await client.create_payload_index(
                collection_name=settings.qdrant_collection,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:  # noqa: BLE001 (index may already exist)
            logger.debug("payload index create skipped", extra={"field": field, "error": str(exc)})
    logger.info("qdrant collection ready", extra={"collection": settings.qdrant_collection})


def _user_filter(user_id: UUID, document_ids: list[UUID] | None) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="user_id", match=models.MatchValue(value=str(user_id)))
    ]
    if document_ids:
        must.append(
            models.FieldCondition(
                key="document_id",
                match=models.MatchAny(any=[str(d) for d in document_ids]),
            )
        )
    return models.Filter(must=must)


async def upsert_chunks(points: list[dict]) -> None:
    """
    Upsert chunk vectors. Each point dict: {id, vector, payload}.
    Payload carries user_id/document_id/chunk_id/page_number/content_preview.
    """
    if not points:
        return
    client = get_qdrant()
    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            models.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ],
        wait=True,
    )


async def search(
    *,
    query_vector: list[float],
    user_id: UUID,
    document_ids: list[UUID] | None,
    top_k: int,
) -> list[dict]:
    """Vector search, always scoped to the user (+ optional document subset)."""
    client = get_qdrant()
    hits = await client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        query_filter=_user_filter(user_id, document_ids),
        limit=top_k,
        with_payload=True,
    )
    return [
        {
            "chunk_id": h.payload.get("chunk_id"),
            "document_id": h.payload.get("document_id"),
            "page_number": h.payload.get("page_number"),
            "content_preview": h.payload.get("content_preview", ""),
            "score": h.score,
        }
        for h in hits
    ]


async def delete_by_document(document_id: UUID) -> None:
    """Remove every vector belonging to a document (used on delete/reindex)."""
    client = get_qdrant()
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(document_id)),
                    )
                ]
            )
        ),
        wait=True,
    )


async def health_check() -> bool:
    try:
        await get_qdrant().get_collections()
        return True
    except Exception:  # noqa: BLE001
        return False
