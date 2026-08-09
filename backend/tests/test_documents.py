"""
End-to-end document tests: upload → ingest → hybrid retrieval → cited answer.

These run against the real pipeline (real PDF parsing, real embeddings, the SQL
vector store) with the extractive LLM provider, so they assert the retrieval
half is genuinely working without needing an API key.
"""
from __future__ import annotations

import asyncio

import pytest


async def _wait_until_ready(client, headers, document_id, timeout: float = 120.0):
    """Poll a document until ingestion finishes; fail loudly if it doesn't."""
    deadline = asyncio.get_running_loop().time() + timeout
    status = "processing"
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(
            f"/api/documents/{document_id}/status", headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        status = body["status"]
        if status != "processing":
            assert status == "ready", f"ingestion failed: {body.get('error_reason')}"
            return body
        await asyncio.sleep(1)
    pytest.fail(f"document stuck in '{status}' after {timeout}s")


class TestUploadValidation:
    async def test_rejects_unsupported_file_type(self, client, user_factory):
        headers, _ = await user_factory()
        response = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("notes.txt", b"plain text", "text/plain")},
        )
        assert response.status_code == 415

    async def test_upload_requires_authentication(self, client, sample_pdf):
        response = await client.post(
            "/api/documents",
            files={"file": ("x.pdf", sample_pdf, "application/pdf")},
        )
        assert response.status_code == 401


class TestIngestionAndRetrieval:
    async def test_upload_ingests_and_reports_chunk_counts(
        self, client, user_factory, sample_pdf
    ):
        headers, _ = await user_factory()
        upload = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("agreement.pdf", sample_pdf, "application/pdf")},
        )
        assert upload.status_code == 201
        assert upload.json()["status"] == "processing"

        await _wait_until_ready(client, headers, upload.json()["id"])

        listing = await client.get("/api/documents", headers=headers)
        document = next(d for d in listing.json() if d["id"] == upload.json()["id"])
        assert document["status"] == "ready"
        assert document["chunk_count"] > 0
        assert document["page_count"] >= 1

    async def test_question_returns_grounded_answer_with_citations(
        self, client, user_factory, sample_pdf
    ):
        headers, _ = await user_factory()
        upload = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("agreement.pdf", sample_pdf, "application/pdf")},
        )
        document_id = upload.json()["id"]
        await _wait_until_ready(client, headers, document_id)

        conversation = await client.post(
            "/api/conversations",
            headers=headers,
            json={"title": "Terms", "document_scope": [document_id]},
        )
        assert conversation.status_code == 201

        answer = await client.post(
            f"/api/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={"question": "What is the payment term?", "stream": False},
        )
        assert answer.status_code == 200
        message = answer.json()["message"]

        # Retrieval must actually find the clause — this is the regression that
        # previously made every answer "I couldn't find anything relevant".
        # Asserting on the citation rather than the prose keeps this valid for
        # any LLM provider (or the extractive fallback used in CI).
        assert message["citations"], "a grounded answer must carry citations"
        citation = message["citations"][0]
        assert citation["filename"] == "agreement.pdf"
        assert citation["page"] == 1
        assert "Net 30" in citation["snippet"], citation["snippet"]

    async def test_question_with_no_documents_says_so(self, client, user_factory):
        headers, _ = await user_factory()
        conversation = await client.post(
            "/api/conversations", headers=headers, json={"title": "Empty"}
        )
        answer = await client.post(
            f"/api/conversations/{conversation.json()['id']}/messages",
            headers=headers,
            json={"question": "What are the payment terms?", "stream": False},
        )
        assert answer.status_code == 200
        assert answer.json()["message"]["citations"] == []

    async def test_conversation_history_is_persisted(
        self, client, user_factory, sample_pdf
    ):
        headers, _ = await user_factory()
        upload = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("agreement.pdf", sample_pdf, "application/pdf")},
        )
        await _wait_until_ready(client, headers, upload.json()["id"])

        conversation = await client.post(
            "/api/conversations", headers=headers, json={"title": "History"}
        )
        conversation_id = conversation.json()["id"]
        await client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=headers,
            json={"question": "What is the uptime guarantee?", "stream": False},
        )

        messages = await client.get(
            f"/api/conversations/{conversation_id}/messages", headers=headers
        )
        assert messages.status_code == 200
        roles = [m["role"] for m in messages.json()]
        assert roles == ["user", "assistant"]

    async def test_delete_removes_the_document(self, client, user_factory, sample_pdf):
        headers, _ = await user_factory()
        upload = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("temp.pdf", sample_pdf, "application/pdf")},
        )
        document_id = upload.json()["id"]
        await _wait_until_ready(client, headers, document_id)

        assert (
            await client.delete(f"/api/documents/{document_id}", headers=headers)
        ).status_code == 204

        listing = await client.get("/api/documents", headers=headers)
        assert document_id not in [d["id"] for d in listing.json()]


class TestHealth:
    async def test_health_reports_backends_and_stays_ok_without_redis(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()

        # Redis is deliberately unreachable in the test environment; the app is
        # fully functional without it, so overall status must still be ok.
        assert body["dependencies"]["redis"]["ok"] is False
        assert body["dependencies"]["redis"]["required"] is False
        assert body["dependencies"]["database"]["ok"] is True
        assert body["dependencies"]["vector_store"]["backend"] == "sql"
        assert body["status"] == "ok"
