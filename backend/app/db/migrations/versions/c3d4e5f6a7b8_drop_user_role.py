"""Drop the user role column and its enum type.

Every account now owns its own documents and nothing else — authorisation is
ownership, checked in the repository layer, so there is no privilege level left
for this column to express.

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
    # batch_alter_table so this also works on SQLite, which cannot DROP COLUMN
    # in place and needs the table rebuilt.
    with op.batch_alter_table("users") as batch:
        batch.drop_column("role")

    # Postgres keeps the enum type after the last column using it is dropped.
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    user_role = sa.Enum("user", "admin", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("role", user_role, nullable=False, server_default="user")
        )
