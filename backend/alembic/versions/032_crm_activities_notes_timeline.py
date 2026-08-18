"""Alembic: CRM activities, notes, timeline (Phase A step 4).

Revision ID: 032_crm_activities_notes_timeline
Revises: 031_crm_deals
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "032_crm_activities_notes_timeline"
down_revision: Union[str, None] = "031_crm_deals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "deal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.CheckConstraint(
            "type IN ('task', 'call', 'meeting', 'email')",
            name="ck_crm_activities_type",
        ),
    )
    op.create_index("ix_crm_activities_organization_id", "crm_activities", ["organization_id"])
    op.create_index("ix_crm_activities_deal_id", "crm_activities", ["deal_id"])
    op.create_index("ix_crm_activities_contact_id", "crm_activities", ["contact_id"])
    op.create_index("ix_crm_activities_assigned_user_id", "crm_activities", ["assigned_user_id"])

    op.create_table(
        "crm_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "deal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
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
    op.create_index("ix_crm_notes_organization_id", "crm_notes", ["organization_id"])
    op.create_index("ix_crm_notes_deal_id", "crm_notes", ["deal_id"])
    op.create_index("ix_crm_notes_contact_id", "crm_notes", ["contact_id"])

    op.create_table(
        "crm_timeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "deal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_deals.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "payload",
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
    )
    op.create_index(
        "ix_crm_timeline_events_organization_id", "crm_timeline_events", ["organization_id"]
    )
    op.create_index("ix_crm_timeline_events_deal_id", "crm_timeline_events", ["deal_id"])
    op.create_index("ix_crm_timeline_events_contact_id", "crm_timeline_events", ["contact_id"])
    op.create_index(
        "ix_crm_timeline_events_deal_created",
        "crm_timeline_events",
        ["deal_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_timeline_events_deal_created", table_name="crm_timeline_events")
    op.drop_index("ix_crm_timeline_events_contact_id", table_name="crm_timeline_events")
    op.drop_index("ix_crm_timeline_events_deal_id", table_name="crm_timeline_events")
    op.drop_index("ix_crm_timeline_events_organization_id", table_name="crm_timeline_events")
    op.drop_table("crm_timeline_events")

    op.drop_index("ix_crm_notes_contact_id", table_name="crm_notes")
    op.drop_index("ix_crm_notes_deal_id", table_name="crm_notes")
    op.drop_index("ix_crm_notes_organization_id", table_name="crm_notes")
    op.drop_table("crm_notes")

    op.drop_index("ix_crm_activities_assigned_user_id", table_name="crm_activities")
    op.drop_index("ix_crm_activities_contact_id", table_name="crm_activities")
    op.drop_index("ix_crm_activities_deal_id", table_name="crm_activities")
    op.drop_index("ix_crm_activities_organization_id", table_name="crm_activities")
    op.drop_table("crm_activities")
