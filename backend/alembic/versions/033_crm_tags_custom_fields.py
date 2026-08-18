"""Alembic: CRM tags, deal_tags M2M, custom field defs (Phase A step 5).

Revision ID: 033_crm_tags_custom_fields
Revises: 032_crm_activities_notes_timeline
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "033_crm_tags_custom_fields"
down_revision: Union[str, None] = "032_crm_activities_notes_timeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
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
    op.create_index("ix_crm_tags_organization_id", "crm_tags", ["organization_id"])

    op.create_table(
        "crm_deal_tags",
        sa.Column(
            "deal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_tags.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "crm_custom_field_defs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("field_key", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("field_type", sa.String(length=20), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
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
            "entity_type IN ('contact', 'account', 'deal')",
            name="ck_crm_custom_field_defs_entity_type",
        ),
        sa.CheckConstraint(
            "field_type IN ('text', 'number', 'select', 'multiselect', 'date', 'boolean', 'url')",
            name="ck_crm_custom_field_defs_field_type",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "entity_type",
            "field_key",
            name="uq_crm_field_def_key",
        ),
    )
    op.create_index(
        "ix_crm_custom_field_defs_organization_id",
        "crm_custom_field_defs",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_custom_field_defs_entity_type",
        "crm_custom_field_defs",
        ["entity_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_custom_field_defs_entity_type", table_name="crm_custom_field_defs")
    op.drop_index("ix_crm_custom_field_defs_organization_id", table_name="crm_custom_field_defs")
    op.drop_table("crm_custom_field_defs")
    op.drop_table("crm_deal_tags")
    op.drop_index("ix_crm_tags_organization_id", table_name="crm_tags")
    op.drop_table("crm_tags")
