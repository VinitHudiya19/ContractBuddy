"""
Hybrid retrieval: dense vector search (Qdrant) + lexical keyword search (SQL).

Both legs run concurrently, their ranked lists are merged with Reciprocal Rank
Fusion (RRF), and the fused candidates are re-scored by a local cross-encoder.

The lexical leg is dialect-aware: PostgreSQL uses a real `tsvector` GIN index,
SQLite (the zero-setup local mode) uses per-term LIKE matching scored by how
many query terms a chunk contains. Both return a ranked list of chunk ids, so
everything downstream is identical.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import bindparam, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.vector_store import get_vector_store
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.providers.factory import get_embedder

logger = get_logger(__name__)

_RRF_K = 60
_FUSED_LIMIT = 30
_reranker = None

# Very common words carry no signal in a LIKE-based lexical match and would
# match nearly every chunk, so they are dropped before building the query.
_STOPWORDS = frozenset(
    """a an and are as at be by for from has have how in is it its of on or that the
    this to was what when where which who why will with does do did can could should
    would about into over under between all any some my your our their""".split()
)
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-_.']*")


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

    # Only ever search documents this user owns and that finished indexing.
    doc_stmt = select(Document.id, Document.filename).where(
        Document.user_id == user_id, Document.status == DocumentStatus.ready
    )
    if document_scope:
        doc_stmt = doc_stmt.where(Document.id.in_(document_scope))
    doc_rows = (await session.execute(doc_stmt)).all()
    if not doc_rows:
        timings.total_ms = round((time.perf_counter() - started) * 1000, 2)
        return [], timings

    filenames = {str(doc_id): filename for doc_id, filename in doc_rows}
    searchable_ids = [doc_id for doc_id, _ in doc_rows]

    # The two legs are independent (only the keyword leg touches the session),
    # so they run concurrently and the slower one sets the wall-clock cost.
    (vector_ids, timings.vector_ms), (keyword_ids, timings.keyword_ms) = await asyncio.gather(
        _vector_leg(query, user_id, searchable_ids),
        _keyword_leg(session, query, user_id, searchable_ids),
    )

    fused = _rrf_merge(vector_ids, keyword_ids)
    if not fused:
        timings.total_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "retrieval found no candidates",
            extra={"vector_hits": len(vector_ids), "keyword_hits": len(keyword_ids)},
        )
        return [], timings

    candidates = await _hydrate(session, fused, filenames)

    t2 = time.perf_counter()
    top = await _rerank(query, candidates, settings.rerank_top_k)
    timings.rerank_ms = round((time.perf_counter() - t2) * 1000, 2)
    timings.total_ms = round((time.perf_counter() - started) * 1000, 2)

    logger.info(
        "retrieval complete",
        extra={
            "vector_hits": len(vector_ids),
            "keyword_hits": len(keyword_ids),
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
    """
    Dense semantic leg. Qdrant is optional infrastructure — if it is unreachable
    the request degrades to keyword-only rather than failing, but the failure is
    logged loudly so it is never silently mistaken for "no results".
    """
    t = time.perf_counter()
    try:
        embedder = get_embedder()
        vector = await embedder.embed_one(query)
        hits = await get_vector_store().search(
            query_vector=vector,
            user_id=user_id,
            document_ids=document_ids,
            top_k=settings.vector_top_k,
        )
        ids = [str(h["chunk_id"]) for h in hits if h.get("chunk_id")]
        return ids, round((time.perf_counter() - t) * 1000, 2)
    except Exception as exc:
        logger.warning(
            "vector leg unavailable, falling back to keyword-only retrieval",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return [], round((time.perf_counter() - t) * 1000, 2)


def _query_terms(query: str) -> list[str]:
    """Lowercase content words from the query, longest first, capped at 12."""
    words = _WORD_RE.findall(query.lower())
    terms = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    if not terms:  # a query made only of stopwords still deserves an attempt
        terms = [w for w in words if len(w) > 1]
    seen: set[str] = set()
    unique = [t for t in terms if not (t in seen or seen.add(t))]
    unique.sort(key=len, reverse=True)
    return unique[:12]


async def _keyword_leg(
    session: AsyncSession, query: str, user_id: UUID, document_ids: list[UUID]
) -> tuple[list[str], float]:
    """Lexical leg — Postgres full-text search, or per-term matching on SQLite."""
    t = time.perf_counter()
    dialect = session.bind.dialect.name if session.bind is not None else ""
    try:
        if dialect == "postgresql":
            ids = await _keyword_postgres(session, query, user_id, document_ids)
        else:
            ids = await _keyword_generic(session, query, user_id, document_ids)
    except Exception as exc:
        logger.error(
            "keyword leg failed",
            extra={"dialect": dialect, "error": f"{type(exc).__name__}: {exc}"},
        )
        ids = []
    return ids, round((time.perf_counter() - t) * 1000, 2)


async def _keyword_postgres(
    session: AsyncSession, query: str, user_id: UUID, document_ids: list[UUID]
) -> list[str]:
    """`content_tsv` is a generated column with a GIN index (see migrations)."""
    stmt = text(
        """
        SELECT id::text AS chunk_id
        FROM document_chunks
        WHERE user_id = :user_id
          AND document_id IN :doc_ids
          AND content_tsv @@ plainto_tsquery('english', :query)
        ORDER BY ts_rank(content_tsv, plainto_tsquery('english', :query)) DESC
        LIMIT :top_k
        """
    ).bindparams(bindparam("doc_ids", expanding=True))
    result = await session.execute(
        stmt,
        {
            "user_id": str(user_id),
            "doc_ids": [str(d) for d in document_ids],
            "query": query,
            "top_k": settings.keyword_top_k,
        },
    )
    return [row.chunk_id for row in result]


async def _keyword_generic(
    session: AsyncSession, query: str, user_id: UUID, document_ids: list[UUID]
) -> list[str]:
    """
    Portable lexical fallback (SQLite). Scores each chunk by how many distinct
    query terms it contains, which approximates term-frequency ranking well
    enough for demo-scale corpora without any extension or extra service.
    """
    terms = _query_terms(query)
    if not terms:
        return []

    matches = [func.lower(DocumentChunk.content).like(f"%{term}%") for term in terms]
    score_expr = case((matches[0], 1), else_=0)
    for match in matches[1:]:
        score_expr = score_expr + case((match, 1), else_=0)
    score = score_expr.label("match_score")

    stmt = (
        select(DocumentChunk.id, score)
        .where(
            DocumentChunk.user_id == user_id,
            DocumentChunk.document_id.in_(document_ids),
            or_(*matches),
        )
        .order_by(score.desc())
        .limit(settings.keyword_top_k)
    )
    result = await session.execute(stmt)
    return [str(row[0]) for row in result]


def _rrf_merge(vector_ids: list[str], keyword_ids: list[str], k: int = _RRF_K) -> list[str]:
    """
    Reciprocal Rank Fusion: score = sum over legs of 1 / (k + rank).

    Rank-based fusion sidesteps the fact that cosine similarity and ts_rank live
    on completely different scales, so no score normalisation is needed.
    """
    scores: dict[str, float] = {}
    for ranked in (vector_ids, keyword_ids):
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

    return sorted(scores, key=lambda cid: scores[cid], reverse=True)[:_FUSED_LIMIT]


async def _hydrate(
    session: AsyncSession, chunk_ids: list[str], filenames: dict[str, str]
) -> list[RetrievedChunk]:
    """Load full chunk text for the fused ids, preserving fusion order."""
    uuids = []
    for cid in chunk_ids:
        try:
            uuids.append(UUID(cid))
        except (ValueError, AttributeError, TypeError):
            logger.warning("skipping malformed chunk id from search", extra={"chunk_id": cid})
    if not uuids:
        return []

    result = await session.execute(select(DocumentChunk).where(DocumentChunk.id.in_(uuids)))
    chunk_map = {str(c.id): c for c in result.scalars().all()}

    hydrated: list[RetrievedChunk] = []
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
    """
    Cross-encoder reranking. A bi-encoder embeds query and chunk separately; a
    cross-encoder reads the pair together with full attention, which is far more
    accurate but too slow for the whole corpus — hence rerank-after-retrieve.
    """
    global _reranker
    if not settings.rerank_enabled or not chunks:
        return chunks[:top_k]

    try:
        from sentence_transformers import CrossEncoder

        if _reranker is None:
            _reranker = await asyncio.to_thread(
                CrossEncoder, settings.reranker_model, device="cpu"
            )

        pairs = [[query, c.content] for c in chunks]
        scores = await asyncio.to_thread(_reranker.predict, pairs)

        for chunk, score in zip(chunks, scores, strict=True):
            chunk.score = float(score)
        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]
    except Exception as exc:
        # Reranking is a quality boost, not a correctness requirement: keep the
        # RRF order rather than failing the user's question.
        logger.warning(
            "reranker unavailable, returning RRF order",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return chunks[:top_k]
