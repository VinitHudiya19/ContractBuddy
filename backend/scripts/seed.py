"""
Bootstrap seed — creates the initial admin account (idempotent).

Run with:  python -m scripts.seed
Also runs automatically at container boot (docker-entrypoint.sh). Credentials
come from BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD; change them in .env.
"""
from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.enums import UserRole
from app.repositories.user_repo import UserRepository


async def main() -> None:
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(settings.bootstrap_admin_email)
        if existing is not None:
            print(f"[seed] admin already exists: {settings.bootstrap_admin_email}")
            return
        await repo.create(
            email=settings.bootstrap_admin_email,
            hashed_password=hash_password(settings.bootstrap_admin_password),
            full_name="Administrator",
            role=UserRole.admin,
        )
        await session.commit()
        print(f"[seed] admin created: {settings.bootstrap_admin_email}")


if __name__ == "__main__":
    asyncio.run(main())
