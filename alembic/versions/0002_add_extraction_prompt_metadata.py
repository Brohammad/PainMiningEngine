"""Add provider and temperature columns to extractions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extractions",
        sa.Column("provider", sa.String(), nullable=False, server_default="openai"),
    )
    op.add_column(
        "extractions",
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("extractions", "temperature")
    op.drop_column("extractions", "provider")
