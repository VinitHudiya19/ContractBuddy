"""
Alembic environment.

Runs migrations synchronously using a psycopg2-style URL derived from the app's
async DATABASE_URL (we strip the `+asyncpg` driver suffix so Alembic uses the
default sync driver). Target metadata is the app's declarative Base with all
models imported, so autogenerate sees every table.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.session import Base

# Import models so they register on Base.metadata.
import app.models  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic + SQLAlchemy migrations run on a sync driver. Convert the async URL.
sync_url = settings.database_url.replace("+asyncpg", "").replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
