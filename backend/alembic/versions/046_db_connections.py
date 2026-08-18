"""Alembic: organization encrypted SQL DB connections.

Revision ID: 046_db_connections
Revises: 045_audit_logs
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "046_db_connections"
down_revision: Union[str, None] = "045_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_db_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("db_type", sa.String(length=32), nullable=False),
        sa.Column("connection_string_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_organization_db_connections_organization_id",
        "organization_db_connections",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_db_connections_created_by_id",
        "organization_db_connections",
        ["created_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_db_connections_created_by_id",
        table_name="organization_db_connections",
    )
    op.drop_index(
        "ix_organization_db_connections_organization_id",
        table_name="organization_db_connections",
    )
    op.drop_table("organization_db_connections")
