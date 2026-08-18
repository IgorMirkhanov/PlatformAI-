"""Extend admin_audit_logs for org balance adjustments

Revision ID: 021_admin_audit_org
Revises: 020_org_stripe_customer
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "021_admin_audit_org"
down_revision: Union[str, None] = "020_org_stripe_customer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "admin_audit_logs" not in inspector.get_table_names():
        return
    cols = _cols(inspector, "admin_audit_logs")
    if "organization_id" not in cols:
        op.add_column(
            "admin_audit_logs",
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_admin_audit_logs_organization_id",
            "admin_audit_logs",
            ["organization_id"],
        )
    if "details" not in cols:
        op.add_column(
            "admin_audit_logs",
            sa.Column("details", sa.String(length=1024), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = _cols(inspector, "admin_audit_logs")
    if "details" in cols:
        op.drop_column("admin_audit_logs", "details")
    if "organization_id" in cols:
        op.drop_index("ix_admin_audit_logs_organization_id", table_name="admin_audit_logs")
        op.drop_column("admin_audit_logs", "organization_id")
