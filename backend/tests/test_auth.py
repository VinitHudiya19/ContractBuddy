"""
Authentication and access-control tests.

The multi-tenant isolation tests are the important ones: they assert that one
user cannot reach another user's data through any documented endpoint.
"""
from __future__ import annotations


class TestRegistrationAndLogin:
    async def test_register_then_login_returns_token_pair(self, client):
        email = "flow@example.com"
        register = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "Password123", "full_name": "Flow"},
        )
        assert register.status_code == 201

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "Password123"}
        )
        assert login.status_code == 200
        body = login.json()
        assert body["access_token"] and body["refresh_token"]
        assert body["token_type"] == "bearer"

    async def test_duplicate_email_is_rejected(self, client):
        payload = {
            "email": "dupe@example.com",
            "password": "Password123",
            "full_name": "Dupe",
        }
        assert (await client.post("/api/auth/register", json=payload)).status_code == 201
        assert (await client.post("/api/auth/register", json=payload)).status_code == 409

    async def test_wrong_password_is_rejected(self, client, user_factory):
        _, user = await user_factory()
        response = await client.post(
            "/api/auth/login", json={"email": user["email"], "password": "WrongPass1"}
        )
        assert response.status_code == 401

    async def test_short_password_fails_validation(self, client):
        response = await client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc", "full_name": "S"},
        )
        assert response.status_code == 422

    async def test_password_is_never_returned(self, client):
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "secret@example.com",
                "password": "Password123",
                "full_name": "Secret",
            },
        )
        assert "password" not in response.text.lower()


class TestTokenHandling:
    async def test_protected_route_requires_a_token(self, client):
        assert (await client.get("/api/documents")).status_code == 401

    async def test_garbage_token_is_rejected(self, client):
        response = await client.get(
            "/api/documents", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401

    async def test_refresh_rotates_and_invalidates_the_old_token(self, client):
        email = "rotate@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "Password123", "full_name": "Rotate"},
        )
        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "Password123"}
        )
        original = login.json()["refresh_token"]

        first = await client.post("/api/auth/refresh", json={"refresh_token": original})
        assert first.status_code == 200
        assert first.json()["refresh_token"] != original

        # Replaying a rotated token must fail — that is the reuse detection.
        replay = await client.post("/api/auth/refresh", json={"refresh_token": original})
        assert replay.status_code == 401


class TestTenantIsolation:
    async def test_documents_are_not_visible_across_accounts(
        self, client, user_factory, sample_pdf
    ):
        alice_headers, _ = await user_factory()
        bob_headers, _ = await user_factory()

        upload = await client.post(
            "/api/documents",
            headers=alice_headers,
            files={"file": ("alice.pdf", sample_pdf, "application/pdf")},
        )
        assert upload.status_code == 201
        document_id = upload.json()["id"]

        bob_list = await client.get("/api/documents", headers=bob_headers)
        assert bob_list.status_code == 200
        assert document_id not in [d["id"] for d in bob_list.json()]

        # Direct access by id must 404, not 403 — no existence disclosure.
        assert (
            await client.get(
                f"/api/documents/{document_id}/status", headers=bob_headers
            )
        ).status_code == 404
        assert (
            await client.delete(f"/api/documents/{document_id}", headers=bob_headers)
        ).status_code == 404

    async def test_conversations_are_not_visible_across_accounts(
        self, client, user_factory
    ):
        alice_headers, _ = await user_factory()
        bob_headers, _ = await user_factory()

        created = await client.post(
            "/api/conversations", headers=alice_headers, json={"title": "Private"}
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        assert (
            await client.get(
                f"/api/conversations/{conversation_id}/messages", headers=bob_headers
            )
        ).status_code == 404

        assert (
            await client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers=bob_headers,
                json={"question": "Anything secret in here?", "stream": False},
            )
        ).status_code == 404

    async def test_admin_endpoints_reject_regular_users(self, client, user_factory):
        headers, _ = await user_factory()
        assert (await client.get("/api/admin/users", headers=headers)).status_code == 403
        assert (await client.get("/api/admin/stats", headers=headers)).status_code == 403
