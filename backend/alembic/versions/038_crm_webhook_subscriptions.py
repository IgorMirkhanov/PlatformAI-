"""Alembic: CRM outbound webhook subscriptions.

Revision ID: 038_crm_webhook_subscriptions
Revises: 037_crm_usage_metric_types
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "038_crm_webhook_subscriptions"
down_revision: Union[str, None] = "037_crm_usage_metric_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_webhook_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_url", sa.String(length=1024), nullable=False),
        sa.Column(
            "event_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("secret", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
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
    )
    op.create_index(
        "ix_crm_webhook_subscriptions_organization_id",
        "crm_webhook_subscriptions",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_webhook_subscriptions_is_active",
        "crm_webhook_subscriptions",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_webhook_subscriptions_is_active",
        table_name="crm_webhook_subscriptions",
    )
    op.drop_index(
        "ix_crm_webhook_subscriptions_organization_id",
        table_name="crm_webhook_subscriptions",
    )
    op.drop_table("crm_webhook_subscriptions")
