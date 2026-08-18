"""Add JSONB metadata column to admin_audit_logs.

Revision ID: 050_admin_audit_metadata
Revises: 049_llm_models
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "050_admin_audit_metadata"
down_revision: Union[str, None] = "049_llm_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admin_audit_logs",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_audit_logs", "metadata")
