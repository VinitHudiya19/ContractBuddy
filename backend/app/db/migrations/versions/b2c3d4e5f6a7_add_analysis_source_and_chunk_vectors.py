"""add contracts.analysis_source and the chunk_vectors table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-08

`analysis_source` records whether a contract analysis came from the LLM or the
rule-based fallback. `chunk_vectors` backs the built-in SQL vector store used
when Qdrant is not deployed; it stays empty on Qdrant-backed installs.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contracts", sa.Column("analysis_source", sa.String(20), nullable=True))

    op.create_table(
        "chunk_vectors",
        sa.Column("point_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_chunk_vectors_chunk_id", "chunk_vectors", ["chunk_id"])
    op.create_index("ix_chunk_vectors_user_id", "chunk_vectors", ["user_id"])
    op.create_index("ix_chunk_vectors_document_id", "chunk_vectors", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_chunk_vectors_document_id", table_name="chunk_vectors")
    op.drop_index("ix_chunk_vectors_user_id", table_name="chunk_vectors")
    op.drop_index("ix_chunk_vectors_chunk_id", table_name="chunk_vectors")
    op.drop_table("chunk_vectors")
    op.drop_column("contracts", "analysis_source")
