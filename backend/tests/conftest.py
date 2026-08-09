"""
Test fixtures.

Every test runs against a throwaway SQLite file and the SQL vector store, so the
suite needs no Docker, no Postgres, no Qdrant and no network. The environment is
set before `app` is imported because settings are read at import time.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

_TMP_DIR = Path(tempfile.mkdtemp(prefix="contractbuddy-tests-"))

os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP_DIR / 'test.db').as_posix()}",
        "VECTOR_STORE": "sql",
        "UPLOAD_DIR": str(_TMP_DIR / "uploads"),
        "REDIS_URL": "redis://127.0.0.1:6399/0",  # intentionally unreachable
        "GROQ_API_KEY": "",  # force the extractive provider: no network calls
        "JWT_SECRET": "test-secret-not-for-production",
        "RERANK_ENABLED": "false",  # keep the suite fast and offline
        "BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
        "BOOTSTRAP_ADMIN_PASSWORD": "admin-test-pw",
    }
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def initialised_app():
    """Import the app once and run the same startup the server would."""
    from app.db.session import create_tables_if_missing
    from app.db.vector_store import init_vector_store
    from app.main import app
    from app.services.bootstrap import ensure_admin_user

    await create_tables_if_missing()
    await init_vector_store()
    await ensure_admin_user()
    return app


@pytest_asyncio.fixture(loop_scope="session")
async def client(initialised_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=initialised_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def user_factory(client):
    """Register a fresh user and return (auth_headers, user_json)."""

    async def _make(password: str = "Password123") -> tuple[dict, dict]:
        email = f"user-{uuid.uuid4().hex[:10]}@example.com"
        register = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "full_name": "Test User"},
        )
        assert register.status_code == 201, register.text

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}, register.json()

    return _make


@pytest.fixture
def sample_pdf() -> bytes:
    """A small real PDF so the parser is exercised, not mocked."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "SERVICE AGREEMENT",
        'Between Globex Corporation ("Client") and Initech Systems LLC ("Vendor").',
        "1. PAYMENT. Client shall pay Vendor within Net 30 days of invoice.",
        "2. UPTIME. Vendor guarantees 99.9% monthly availability.",
        "3. TERMINATION. Either party may terminate with 45 days notice.",
        "4. LIABILITY. Total liability shall not exceed USD 100,000.",
        "5. CONFIDENTIALITY. Both parties protect confidential information.",
    ]
    y = 72
    for line in lines:
        page.insert_text((60, y), line, fontsize=11)
        y += 20
    data = doc.tobytes()
    doc.close()
    return data
