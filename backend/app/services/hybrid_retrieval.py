"""
Hybrid retrieval: vector search + Postgres full-text search.
Merges legs using Reciprocal Rank Fusion (RRF) and reranks using Cross-Encoder.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db import qdrant_client
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.providers.factory import get_embedder

logger = get_logger(__name__)

_RRF_K = 60
_reranker = None


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None
    content: str
    score: float = 0.0


@dataclass
class StageTimings:
    vector_ms: float = 0.0
    keyword_ms: float = 0.0
    rerank_ms: float = 0.0
    total_ms: float = 0.0


async def retrieve(
    session: AsyncSession,
    *,
    user_id: UUID,
    query: str,
    document_scope: list[UUID] | None = None,
) -> tuple[list[RetrievedChunk], StageTimings]:
    started = time.perf_counter()
    timings = StageTimings()

    # Get documents that are in scope and owned by the user
    doc_stmt = select(Document.id, Document.filename).where(
        Document.user_id == user_id, Document.status == DocumentStatus.ready
    )
    if document_scope:
        doc_stmt = doc_stmt.where(Document.id.in_(document_scope))
    doc_rows = (await session.execute(doc_stmt)).all()
    if not doc_rows:
        return [], timings
    filenames = {str(doc_id): filename for doc_id, filename in doc_rows}
    searchable_ids = [doc_id for doc_id, _ in doc_rows]

    # Run vector and keyword searches concurrently
    t0 = time.perf_counter()
    vector_task = asyncio.create_task(
        _vector_leg(query, user_id, searchable_ids)
    )
    keyword_task = asyncio.create_task(
        _keyword_leg(session, query, user_id, searchable_ids)
    )
    vector_hits, keyword_hits = await asyncio.gather(vector_task, keyword_task)
    timings.vector_ms = vector_hits[1]
    timings.keyword_ms = keyword_hits[1]

    # Merge results using RRF
    fused = _rrf_merge(vector_hits[0], keyword_hits[0])
    if not fused:
        timings.total_ms = round((time.perf_counter() - started) * 1000, 2)
        return [], timings

    # Get chunk contents from database
    candidates = await _hydrate(session, fused, filenames)

    # Rerank candidates using cross encoder
    t2 = time.perf_counter()
    top = await _rerank(query, candidates, settings.rerank_top_k)
    timings.rerank_ms = round((time.perf_counter() - t2) * 1000, 2)

    timings.total_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "retrieval complete",
        extra={
            "candidates": len(candidates),
            "returned": len(top),
            "vector_ms": timings.vector_ms,
            "keyword_ms": timings.keyword_ms,
            "rerank_ms": timings.rerank_ms,
        },
    )
    return top, timings


async def _vector_leg(
    query: str, user_id: UUID, document_ids: list[UUID]
) -> tuple[list[str], float]:
    # Semantic search leg using Qdrant
    t = time.perf_counter()
    embedder = get_embedder()
    vector = await embedder.embed_query(query)
    hits = await qdrant_client.search_vectors(
        user_id=user_id,
        document_ids=document_ids,
        vector=vector,
        top_k=settings.vector_top_k,
    )
    ids = [str(h.payload["chunk_id"]) for h in hits]
    return ids, round((time.perf_counter() - t) * 1000, 2)


async def _keyword_leg(
    session: AsyncSession, query: str, user_id: UUID, document_ids: list[UUID]
) -> tuple[list[str], float]:
    # Lexical search leg using Postgres text search GIN index
    t = time.perf_counter()
    stmt = (
        text(
            """
            SELECT id::text AS chunk_id
            FROM document_chunks
            WHERE user_id = :user_id
              AND document_id IN :doc_ids
              AND content_tsv @@ plainto_tsquery('english', :query)
            ORDER BY ts_rank(content_tsv, plainto_tsquery('english', :query)) DESC
            LIMIT :top_k
            """
        )
        .bindparams(bindparam("doc_ids", expanding=True))
    )
    result = await session.execute(
        stmt,
        {
            "user_id": str(user_id),
            "doc_ids": [str(d) for d in document_ids],
            "query": query,
            "top_k": settings.keyword_top_k,
        },
    )
    ids = [row.chunk_id for row in result]
    return ids, round((time.perf_counter() - t) * 1000, 2)


def _rrf_merge(vector_ids: list[str], keyword_ids: list[str], k: int = _RRF_K) -> list[str]:
    # Reciprocal Rank Fusion helper
    scores: dict[str, float] = {}
    for rank, cid in enumerate(vector_ids):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    for rank, cid in enumerate(keyword_ids):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    return sorted_ids[:30]


async def _hydrate(
    session: AsyncSession, chunk_ids: list[str], filenames: dict[str, str]
) -> list[RetrievedChunk]:
    # Load chunk data from database
    result = await session.execute(
        select(DocumentChunk).where(DocumentChunk.id.in_([UUID(cid) for cid in chunk_ids]))
    )
    chunks = result.scalars().all()
    chunk_map = {str(c.id): c for c in chunks}

    hydrated = []
    for cid in chunk_ids:
        chunk = chunk_map.get(cid)
        if chunk is None:
            continue
        doc_id = str(chunk.document_id)
        hydrated.append(
            RetrievedChunk(
                chunk_id=cid,
                document_id=doc_id,
                filename=filenames.get(doc_id, "Unknown"),
                page_number=chunk.page_number,
                content=chunk.content,
            )
        )
    return hydrated


async def _rerank(query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
    # Reranking using cross encoder model
    global _reranker
    if not settings.rerank_enabled or not chunks:
        return chunks[:top_k]

    from sentence_transformers import CrossEncoder

    if _reranker is None:
        _reranker = CrossEncoder(settings.reranker_model, device="cpu")

    pairs = [[query, c.content] for c in chunks]
    loop = asyncio.get_running_loop()
    scores = await loop.run_in_executor(None, _reranker.predict, pairs)

    for chunk, score in zip(chunks, scores):
        chunk.score = float(score)

    sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
    return sorted_chunks[:top_k]
