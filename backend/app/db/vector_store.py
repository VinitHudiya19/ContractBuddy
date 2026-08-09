"""
Pluggable vector store.

Two backends implement the same small interface, so nothing in the retrieval or
ingestion code knows which one is active:

* ``QdrantVectorStore`` — the production path. Real ANN index, multi-tenant
  isolation enforced by payload filters applied *before* the similarity search.
* ``SqlVectorStore``    — the zero-setup path. Vectors live in a table next to
  the chunks and similarity is a brute-force dot product in NumPy. O(n) per
  query, which is fine for a demo corpus and keeps `git clone && run` working
  with no Docker, but it is the reason Qdrant exists for real workloads.

``VECTOR_STORE=auto`` (the default) probes Qdrant once at startup and falls back
to the SQL store when it is not reachable.
"""
from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

_store: VectorStore | None = None


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class VectorStore(ABC):
    """Interface both backends implement."""

    name: str = "base"

    @abstractmethod
    async def ensure_ready(self) -> None:
        """Create whatever the backend needs. Must be idempotent."""

    @abstractmethod
    async def upsert(self, points: list[dict]) -> None:
        """Insert/replace points: {id, vector, payload{user_id, document_id, chunk_id, ...}}."""

    @abstractmethod
    async def search(
        self,
        *,
        query_vector: list[float],
        user_id: UUID,
        document_ids: list[UUID] | None,
        top_k: int,
    ) -> list[dict]:
        """Top-k nearest chunks, always scoped to one user."""

    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> None:
        """Drop every vector belonging to a document."""

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    async def close(self) -> None:
        return None


class QdrantVectorStore(VectorStore):
    name = "qdrant"

    async def ensure_ready(self) -> None:
        from app.db import qdrant_client

        await qdrant_client.ensure_collection()

    async def upsert(self, points: list[dict]) -> None:
        from app.db import qdrant_client

        await qdrant_client.upsert_chunks(points)

    async def search(
        self,
        *,
        query_vector: list[float],
        user_id: UUID,
        document_ids: list[UUID] | None,
        top_k: int,
    ) -> list[dict]:
        from app.db import qdrant_client

        return await qdrant_client.search(
            query_vector=query_vector,
            user_id=user_id,
            document_ids=document_ids,
            top_k=top_k,
        )

    async def delete_by_document(self, document_id: UUID) -> None:
        from app.db import qdrant_client

        await qdrant_client.delete_by_document(document_id)

    async def health_check(self) -> bool:
        from app.db import qdrant_client

        return await qdrant_client.health_check()

    async def close(self) -> None:
        from app.db import qdrant_client

        await qdrant_client.close_qdrant()


class SqlVectorStore(VectorStore):
    """
    Brute-force store backed by the main database.

    Embeddings are L2-normalised by the embedding provider, so cosine
    similarity reduces to a plain dot product and the whole search is one
    matrix multiply over the rows the tenant filter already narrowed down.

    Note: writes use their own session (the interface is shared with Qdrant,
    which has no notion of one). Callers must therefore not hold an uncommitted
    write transaction while calling in — on SQLite that deadlocks against
    itself. Commit first, or call before starting the write.
    """

    name = "sql"

    async def ensure_ready(self) -> None:
        from app.db.session import Base, engine
        from app.models.document import ChunkVector  # noqa: F401 — registers the table

        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all, tables=[ChunkVector.__table__]
            )

    async def upsert(self, points: list[dict]) -> None:
        if not points:
            return
        from app.models.document import ChunkVector

        async with AsyncSessionLocal() as session:
            point_ids = [UUID(str(p["id"])) for p in points]
            await session.execute(
                delete(ChunkVector).where(ChunkVector.point_id.in_(point_ids))
            )
            for point in points:
                payload = point["payload"]
                session.add(
                    ChunkVector(
                        point_id=UUID(str(point["id"])),
                        chunk_id=UUID(str(payload["chunk_id"])),
                        user_id=UUID(str(payload["user_id"])),
                        document_id=UUID(str(payload["document_id"])),
                        page_number=payload.get("page_number"),
                        content_preview=payload.get("content_preview", ""),
                        vector=_pack(point["vector"]),
                    )
                )
            await session.commit()

    async def search(
        self,
        *,
        query_vector: list[float],
        user_id: UUID,
        document_ids: list[UUID] | None,
        top_k: int,
    ) -> list[dict]:
        import numpy as np

        from app.models.document import ChunkVector

        async with AsyncSessionLocal() as session:
            # Tenant filter first — a user can only ever score their own rows.
            stmt = select(ChunkVector).where(ChunkVector.user_id == user_id)
            if document_ids:
                stmt = stmt.where(ChunkVector.document_id.in_(document_ids))
            rows = (await session.execute(stmt)).scalars().all()

        if not rows:
            return []

        query = np.asarray(query_vector, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm:
            query = query / norm

        matrix = np.frombuffer(b"".join(r.vector for r in rows), dtype=np.float32)
        matrix = matrix.reshape(len(rows), -1)
        if matrix.shape[1] != query.shape[0]:
            logger.error(
                "embedding dimension mismatch — reindex after changing models",
                extra={"stored_dim": int(matrix.shape[1]), "query_dim": int(query.shape[0])},
            )
            return []

        scores = matrix @ query
        best = np.argsort(-scores)[:top_k]
        return [
            {
                "chunk_id": str(rows[i].chunk_id),
                "document_id": str(rows[i].document_id),
                "page_number": rows[i].page_number,
                "content_preview": rows[i].content_preview or "",
                "score": float(scores[i]),
            }
            for i in best
        ]

    async def delete_by_document(self, document_id: UUID) -> None:
        from app.models.document import ChunkVector

        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(ChunkVector).where(ChunkVector.document_id == document_id)
            )
            await session.commit()

    async def health_check(self) -> bool:
        try:
            from app.models.document import ChunkVector

            async with AsyncSessionLocal() as session:
                await session.execute(select(ChunkVector.point_id).limit(1))
            return True
        except Exception as exc:
            logger.error("sql vector store unhealthy", extra={"error": str(exc)})
            return False


async def init_vector_store() -> VectorStore:
    """
    Pick and prepare the backend. Called once from the app lifespan.

    `auto` prefers Qdrant and degrades to the SQL store, so the app starts and
    stays fully functional whether or not the docker-compose stack is running.
    """
    global _store
    mode = settings.vector_store.lower()

    if mode in ("qdrant", "auto"):
        candidate = QdrantVectorStore()
        try:
            await candidate.ensure_ready()
            _store = candidate
            logger.info("vector store ready", extra={"backend": "qdrant"})
            return _store
        except Exception as exc:
            if mode == "qdrant":
                raise
            logger.warning(
                "qdrant unreachable, using built-in SQL vector store",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )

    _store = SqlVectorStore()
    await _store.ensure_ready()
    logger.info("vector store ready", extra={"backend": "sql"})
    return _store


def get_vector_store() -> VectorStore:
    """Active backend. Falls back to the SQL store if startup never ran."""
    global _store
    if _store is None:
        _store = SqlVectorStore()
    return _store


async def close_vector_store() -> None:
    global _store
    if _store is not None:
        await _store.close()
        _store = None
