"""Alembic: CRM automation rules (Phase B step 1).

Revision ID: 035_crm_automation_rules
Revises: 034_crm_settings
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "035_crm_automation_rules"
down_revision: Union[str, None] = "034_crm_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_automation_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("trigger_type", sa.String(length=50), nullable=False),
        sa.Column(
            "trigger_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
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
        sa.CheckConstraint(
            "trigger_type IN ("
            "'stage_entered', 'field_changed', 'tag_added', "
            "'no_activity_for', 'deal_created')",
            name="ck_crm_automation_rules_trigger_type",
        ),
    )
    op.create_index(
        "ix_crm_automation_rules_organization_id",
        "crm_automation_rules",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_automation_rules_is_active",
        "crm_automation_rules",
        ["is_active"],
    )
    op.create_index(
        "ix_crm_automation_rules_trigger_type",
        "crm_automation_rules",
        ["trigger_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_automation_rules_trigger_type", table_name="crm_automation_rules")
    op.drop_index("ix_crm_automation_rules_is_active", table_name="crm_automation_rules")
    op.drop_index("ix_crm_automation_rules_organization_id", table_name="crm_automation_rules")
    op.drop_table("crm_automation_rules")
