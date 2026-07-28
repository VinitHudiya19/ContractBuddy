import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_contract_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register user first (ignore 400/409 if already exists)
        try:
            reg_resp = await client.post(
                "/api/auth/register",
                json={
                    "email": "hudiyavp@rknec.edu",
                    "password": "Password123",
                    "full_name": "vinit hudiya",
                },
            )
        except Exception as e:
            print("Registration note:", e)

        # 2. Login
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "hudiyavp@rknec.edu", "password": "Password123"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json()["access_token"]
        assert token, "No access token returned"

        # 3. Upload contract & test AI extraction
        files = {
            "file": (
                "contract.txt",
                b"This Agreement is between Acme Corp (Client) and CloudProvider LLC (Vendor). Payment terms: Net 30. SLA 99.9% uptime requirement.",
                "text/plain",
            )
        }
        data = {"title": "Master Cloud SaaS Agreement"}
        headers = {"Authorization": f"Bearer {token}"}

        upload_resp = await client.post(
            "/api/contracts/", data=data, files=files, headers=headers
        )
        assert upload_resp.status_code in (200, 201), f"Upload failed: {upload_resp.text}"
        c = upload_resp.json()

        assert c.get("title") == "Master Cloud SaaS Agreement"
        assert "health_score" in c
        assert "risk_score" in c
        assert "missing_clauses" in c

