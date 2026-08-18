"""Alembic: organization encrypted LLM API keys.

Revision ID: 048_organization_api_keys
Revises: 047_billing_reference_unique
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "048_organization_api_keys"
down_revision: Union[str, None] = "047_billing_reference_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            name="uq_organization_api_keys_org_provider",
        ),
    )
    op.create_index(
        "ix_organization_api_keys_organization_id",
        "organization_api_keys",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_api_keys_provider",
        "organization_api_keys",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_organization_api_keys_provider", table_name="organization_api_keys")
    op.drop_index(
        "ix_organization_api_keys_organization_id",
        table_name="organization_api_keys",
    )
    op.drop_table("organization_api_keys")
