"""Add normalized content hash and processing history.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add duplicate-detection columns and processing history."""

    op.add_column(
        "normalized_documents",
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        "ix_normalized_documents_content_hash",
        "normalized_documents",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_normalized_documents_url",
        "normalized_documents",
        ["url"],
        unique=False,
    )

    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("input_url", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("normalized_content_hash", sa.String(length=64), nullable=True),
        sa.Column("normalized_document_id", sa.Uuid(), nullable=True),
        sa.Column("complaint_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duplicate_match", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["complaint_id"],
            ["extractions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_document_id"],
            ["normalized_documents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_runs_content_hash",
        "processing_runs",
        ["normalized_content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_processing_runs_input_url",
        "processing_runs",
        ["input_url"],
        unique=False,
    )
    op.create_index(
        "ix_processing_runs_platform_external_id",
        "processing_runs",
        ["platform", "external_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove processing history and normalized content hash."""

    op.drop_index(
        "ix_processing_runs_platform_external_id",
        table_name="processing_runs",
    )
    op.drop_index(
        "ix_processing_runs_input_url",
        table_name="processing_runs",
    )
    op.drop_index(
        "ix_processing_runs_content_hash",
        table_name="processing_runs",
    )
    op.drop_table("processing_runs")
    op.drop_index(
        "ix_normalized_documents_url",
        table_name="normalized_documents",
    )
    op.drop_index(
        "ix_normalized_documents_content_hash",
        table_name="normalized_documents",
    )
    op.drop_column("normalized_documents", "content_hash")
