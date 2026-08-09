"""
Async SQLAlchemy engine and session factory.

Works against PostgreSQL (docker-compose / production) and SQLite (the
zero-setup local mode). SQLite gets WAL journaling and a busy timeout so that
background ingestion and live API requests can write concurrently instead of
tripping over "database is locked".
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if settings.is_sqlite:
    # Wait rather than fail when another connection holds the write lock.
    _engine_kwargs["connect_args"] = {"timeout": 30}

engine = create_async_engine(settings.resolved_database_url, **_engine_kwargs)

if settings.is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
        # WAL lets readers run while a writer holds the lock; the busy timeout
        # makes concurrent writers queue instead of raising immediately.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_tables_if_missing() -> None:
    """
    Bring a SQLite database up to date with the ORM metadata.

    Postgres deployments use Alembic (`alembic upgrade head`) as the source of
    truth. This exists so the local mode boots on a clean checkout with no
    migration step, and so an existing local database picks up newly added
    columns instead of failing on the next insert.

    It is deliberately additive only: it creates missing tables and appends
    missing nullable columns. It never drops or retypes anything.
    """
    # Imported for the side effect of registering every model on Base.metadata.
    from app.models import contract, conversation, document, user  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(connection) -> None:
    """Append columns the ORM knows about but the existing tables lack."""
    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateColumn

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable and column.default is None:
                # SQLite cannot add a NOT NULL column without a default.
                logger.warning(
                    "cannot auto-add non-nullable column; run a migration",
                    extra={"table": table.name, "column": column.name},
                )
                continue
            ddl = CreateColumn(column).compile(connection.engine)
            connection.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN {ddl}")
            logger.info(
                "added missing column",
                extra={"table": table.name, "column": column.name},
            )
