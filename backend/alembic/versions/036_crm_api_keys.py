"""Alembic: CRM API keys for public inbound API.

Revision ID: 036_crm_api_keys
Revises: 035_crm_automation_rules
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "036_crm_api_keys"
down_revision: Union[str, None] = "035_crm_automation_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("key_hash", name="uq_crm_api_keys_key_hash"),
    )
    op.create_index(
        "ix_crm_api_keys_organization_id",
        "crm_api_keys",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_api_keys_key_hash",
        "crm_api_keys",
        ["key_hash"],
    )
    op.create_index(
        "ix_crm_api_keys_is_active",
        "crm_api_keys",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_api_keys_is_active", table_name="crm_api_keys")
    op.drop_index("ix_crm_api_keys_key_hash", table_name="crm_api_keys")
    op.drop_index("ix_crm_api_keys_organization_id", table_name="crm_api_keys")
    op.drop_table("crm_api_keys")
