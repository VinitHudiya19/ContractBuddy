"""
Operational behaviour: crash recovery, paging, and upload limits.

These cover what happens when things go wrong or get large, rather than the
happy path in test_documents.py.
"""
from __future__ import annotations

from uuid import UUID

import pytest


async def _insert_documents(user_id: str, count: int, status: str = "ready") -> list[UUID]:
    """Write document rows straight to the database, skipping ingestion."""
    from app.db.session import AsyncSessionLocal
    from app.models.document import Document
    from app.models.enums import DocumentStatus, FileType

    documents = [
        Document(
            user_id=UUID(user_id),
            filename=f"doc-{i}.pdf",
            file_type=FileType.pdf,
            file_size_bytes=1024,
            status=DocumentStatus(status),
        )
        for i in range(count)
    ]
    async with AsyncSessionLocal() as session:
        session.add_all(documents)
        # Ids are assigned on flush, so read them before the session closes.
        await session.flush()
        ids = [d.id for d in documents]
        await session.commit()
    return ids


class TestCrashRecovery:
    async def test_interrupted_ingestion_is_marked_failed(self, client, user_factory):
        """A document left on 'processing' by a dead process must not stay there."""
        from app.services.recovery import INTERRUPTED_REASON, recover_interrupted_ingestions

        headers, user = await user_factory()
        (document_id,) = await _insert_documents(user["id"], 1, status="processing")

        recovered = await recover_interrupted_ingestions()
        assert recovered >= 1

        response = await client.get(f"/api/documents/{document_id}/status", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_reason"] == INTERRUPTED_REASON

    async def test_recovery_leaves_finished_documents_alone(self, client, user_factory):
        from app.services.recovery import recover_interrupted_ingestions

        headers, user = await user_factory()
        (document_id,) = await _insert_documents(user["id"], 1, status="ready")

        await recover_interrupted_ingestions()

        response = await client.get(f"/api/documents/{document_id}/status", headers=headers)
        assert response.json()["status"] == "ready"

    async def test_staging_sweep_removes_orphaned_uploads(self):
        from app.services.ingestion import upload_dir
        from app.services.recovery import sweep_staging_dir

        orphan = upload_dir() / "orphaned-upload.pdf"
        orphan.write_bytes(b"%PDF-1.4 leftover")

        removed = sweep_staging_dir()

        assert removed >= 1
        assert not orphan.exists()


class TestPagination:
    async def test_limit_and_offset_walk_the_list(self, client, user_factory):
        headers, user = await user_factory()
        await _insert_documents(user["id"], 5)

        first = await client.get("/api/documents?limit=2&offset=0", headers=headers)
        second = await client.get("/api/documents?limit=2&offset=2", headers=headers)
        assert first.status_code == 200
        assert len(first.json()) == 2
        assert len(second.json()) == 2

        # Pages must not overlap, or the UI would show the same document twice.
        first_ids = {d["id"] for d in first.json()}
        assert first_ids.isdisjoint({d["id"] for d in second.json()})

    async def test_rejects_a_limit_above_the_cap(self, client, user_factory):
        from app.api.v1.pagination import MAX_PAGE_SIZE

        headers, _ = await user_factory()
        response = await client.get(
            f"/api/documents?limit={MAX_PAGE_SIZE + 1}", headers=headers
        )
        assert response.status_code == 422

    async def test_conversations_are_paged_too(self, client, user_factory):
        headers, _ = await user_factory()
        for i in range(3):
            created = await client.post(
                "/api/conversations", headers=headers, json={"title": f"chat {i}"}
            )
            assert created.status_code == 201, created.text

        response = await client.get("/api/conversations?limit=2", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestUploadLimits:
    @pytest.fixture
    def tiny_limit(self, monkeypatch):
        """Shrink the cap so the test doesn't have to push 20MB through the app."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_upload_size_mb", 1)
        return settings

    async def test_oversized_document_is_rejected(self, client, user_factory, tiny_limit):
        headers, _ = await user_factory()
        payload = b"x" * (2 * 1024 * 1024)

        response = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("big.pdf", payload, "application/pdf")},
        )
        assert response.status_code == 413

    async def test_rejected_upload_leaves_no_file_behind(
        self, client, user_factory, tiny_limit
    ):
        """The partial write has to be cleaned up, or disk fills with rejects."""
        from app.services.ingestion import upload_dir

        headers, _ = await user_factory()
        before = set(upload_dir().iterdir())

        await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("big.pdf", b"x" * (2 * 1024 * 1024), "application/pdf")},
        )

        assert set(upload_dir().iterdir()) == before

    async def test_oversized_contract_is_rejected(self, client, user_factory, tiny_limit):
        """Contracts go through the same helper, so they get the same limit."""
        headers, _ = await user_factory()

        response = await client.post(
            "/api/contracts",
            headers=headers,
            data={"title": "Big Contract"},
            files={"file": ("big.txt", b"x" * (2 * 1024 * 1024), "text/plain")},
        )
        assert response.status_code == 413
