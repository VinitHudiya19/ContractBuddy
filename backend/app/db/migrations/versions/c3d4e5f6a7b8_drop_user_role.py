"""Drop the user role column and its enum type.

There is no admin any more. Every account only touches its own documents, and
the repositories already check that, so the column has nothing left to say.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table rebuilds the table, which SQLite needs since it
    # cannot DROP COLUMN directly.
    with op.batch_alter_table("users") as batch:
        batch.drop_column("role")

    # Postgres keeps the enum type around after the column is gone.
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    user_role = sa.Enum("user", "admin", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("role", user_role, nullable=False, server_default="user")
        )
