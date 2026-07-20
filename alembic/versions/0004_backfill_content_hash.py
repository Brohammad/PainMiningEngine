"""Backfill normalized document content hashes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-20
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from backend.app.storage.hash import content_hash

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalized_row_hash(title: str, content: str, comments: object) -> str:
    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "comments": comments if isinstance(comments, list) else [],
    }
    return content_hash(payload)


def upgrade() -> None:
    """Populate content_hash for rows created before duplicate detection."""

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, title, content, comments
            FROM normalized_documents
            WHERE content_hash = ''
            """
        )
    )
    for row in rows:
        row_hash = _normalized_row_hash(row.title, row.content, row.comments)
        connection.execute(
            sa.text(
                """
                UPDATE normalized_documents
                SET content_hash = :content_hash
                WHERE id = :document_id
                """
            ),
            {"content_hash": row_hash, "document_id": row.id},
        )


def downgrade() -> None:
    """Reset backfilled hashes to the migration placeholder."""

    op.execute(
        sa.text(
            """
            UPDATE normalized_documents
            SET content_hash = ''
            """
        )
    )
