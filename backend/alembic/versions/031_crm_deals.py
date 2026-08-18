"""Alembic: native CRM deals (Phase A step 3).

Revision ID: 031_crm_deals
Revises: 030_crm_accounts_contacts
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "031_crm_deals"
down_revision: Union[str, None] = "030_crm_accounts_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_deals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_pipelines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_stages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KZT"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'won', 'lost')",
            name="ck_crm_deals_status",
        ),
    )
    op.create_index("ix_crm_deals_organization_id", "crm_deals", ["organization_id"])
    op.create_index("ix_crm_deals_pipeline_id", "crm_deals", ["pipeline_id"])
    op.create_index("ix_crm_deals_stage_id", "crm_deals", ["stage_id"])
    op.create_index("ix_crm_deals_contact_id", "crm_deals", ["contact_id"])
    op.create_index("ix_crm_deals_account_id", "crm_deals", ["account_id"])
    op.create_index("ix_crm_deals_bot_id", "crm_deals", ["bot_id"])
    op.create_index("ix_crm_deals_assigned_user_id", "crm_deals", ["assigned_user_id"])
    op.create_index("ix_crm_deals_status", "crm_deals", ["status"])
    op.create_index(
        "ix_crm_deals_org_pipeline_stage",
        "crm_deals",
        ["organization_id", "pipeline_id", "stage_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_deals_org_pipeline_stage", table_name="crm_deals")
    op.drop_index("ix_crm_deals_status", table_name="crm_deals")
    op.drop_index("ix_crm_deals_assigned_user_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_bot_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_account_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_contact_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_stage_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_pipeline_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_organization_id", table_name="crm_deals")
    op.drop_table("crm_deals")
