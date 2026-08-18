"""Alembic: native CRM accounts + contacts (Phase A step 2).

Revision ID: 030_crm_accounts_contacts
Revises: 029_crm_pipelines_stages

Prompt named this ``024_…`` / down_revision ``023_…``; those revision ids are
already taken in this repo. Continues the real Alembic chain after pipelines.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "030_crm_accounts_contacts"
down_revision: Union[str, None] = "029_crm_pipelines_stages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
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
    )
    op.create_index("ix_crm_accounts_organization_id", "crm_accounts", ["organization_id"])

    op.create_table(
        "crm_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("first_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column(
            "linked_client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
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
        sa.UniqueConstraint("linked_client_id", name="uq_crm_contacts_linked_client_id"),
    )
    op.create_index("ix_crm_contacts_organization_id", "crm_contacts", ["organization_id"])
    op.create_index("ix_crm_contacts_account_id", "crm_contacts", ["account_id"])
    op.create_index("ix_crm_contacts_linked_client_id", "crm_contacts", ["linked_client_id"])


def downgrade() -> None:
    op.drop_index("ix_crm_contacts_linked_client_id", table_name="crm_contacts")
    op.drop_index("ix_crm_contacts_account_id", table_name="crm_contacts")
    op.drop_index("ix_crm_contacts_organization_id", table_name="crm_contacts")
    op.drop_table("crm_contacts")
    op.drop_index("ix_crm_accounts_organization_id", table_name="crm_accounts")
    op.drop_table("crm_accounts")
