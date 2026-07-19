"""Create immutable pipeline stage tables.

Revision ID: 0001
Revises:
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Create raw, normalized, and extraction stage tables."""

    op.create_table(
        "raw_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("payload", JSON_DOCUMENT, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "external_id",
            name="uq_raw_sources_platform_external_id",
        ),
    )

    op.create_table(
        "normalized_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_source_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("comments", JSON_DOCUMENT, nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("community", sa.String(), nullable=True),
        sa.Column("metadata", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "normalized_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_source_id"],
            ["raw_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "external_id",
            name="uq_normalized_documents_platform_external_id",
        ),
        sa.UniqueConstraint(
            "raw_source_id",
            name="uq_normalized_documents_raw_source_id",
        ),
    )

    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("result", JSON_DOCUMENT, nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["normalized_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "result_hash",
            name="uq_extractions_document_result_hash",
        ),
    )
    op.create_index(
        "ix_extractions_document_extracted_at",
        "extractions",
        ["document_id", "extracted_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop extraction, normalized, and raw stage tables."""

    op.drop_index(
        "ix_extractions_document_extracted_at",
        table_name="extractions",
    )
    op.drop_table("extractions")
    op.drop_table("normalized_documents")
    op.drop_table("raw_sources")
