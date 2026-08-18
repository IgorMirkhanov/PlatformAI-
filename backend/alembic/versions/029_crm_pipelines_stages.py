"""Alembic: native CRM pipelines + stages (Phase A step 1).

Revision ID: 029_crm_pipelines_stages
Revises: 028_db_indexes_opt

Note: CRM_INTEGRATION_SPEC / Phase-A prompt named this ``023_…``, but that
revision id is already taken by ``023_llm_usage_suspend``. Current head is
``028_db_indexes_opt``, so this migration continues the real chain as 029.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "029_crm_pipelines_stages"
down_revision: Union[str, None] = "028_db_indexes_opt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
    op.create_index("ix_crm_pipelines_organization_id", "crm_pipelines", ["organization_id"])

    op.create_table(
        "crm_stages",
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
            sa.ForeignKey("crm_pipelines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("is_won", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_lost", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
    op.create_index("ix_crm_stages_organization_id", "crm_stages", ["organization_id"])
    op.create_index("ix_crm_stages_pipeline_id", "crm_stages", ["pipeline_id"])
    # At most one won / lost stage per pipeline (race-safe).
    op.execute(
        "CREATE UNIQUE INDEX uq_crm_stages_pipeline_won "
        "ON crm_stages (pipeline_id) WHERE is_won IS TRUE"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_crm_stages_pipeline_lost "
        "ON crm_stages (pipeline_id) WHERE is_lost IS TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_crm_stages_pipeline_lost")
    op.execute("DROP INDEX IF EXISTS uq_crm_stages_pipeline_won")
    op.drop_index("ix_crm_stages_pipeline_id", table_name="crm_stages")
    op.drop_index("ix_crm_stages_organization_id", table_name="crm_stages")
    op.drop_table("crm_stages")
    op.drop_index("ix_crm_pipelines_organization_id", table_name="crm_pipelines")
    op.drop_table("crm_pipelines")
