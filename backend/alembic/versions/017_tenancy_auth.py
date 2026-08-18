"""tenancy projects + auth flags + org slug

Revision ID: 017_tenancy_auth
Revises: None
Create Date: 2026-07-16

Idempotent additive migration for existing deployments that already have
core tables from SQL bootstrap / hand-written migrations/*.sql.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_tenancy_auth"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "is_active" not in cols:
            op.add_column(
                "users",
                sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            )
        if "is_verified" not in cols:
            op.add_column(
                "users",
                sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
            )

    if "companies" in tables:
        cols = {c["name"] for c in inspector.get_columns("companies")}
        if "slug" not in cols:
            op.add_column("companies", sa.Column("slug", sa.String(length=64), nullable=True))
            op.create_index("ix_companies_slug", "companies", ["slug"], unique=True)

    if "projects" not in tables and "companies" in tables:
        op.create_table(
            "projects",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
        )
        op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
        op.create_index("ix_projects_slug", "projects", ["slug"])

    if "bots" in tables:
        cols = {c["name"] for c in inspector.get_columns("bots")}
        if "organization_id" not in cols:
            op.add_column(
                "bots",
                sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                "fk_bots_organization_id_companies",
                "bots",
                "companies",
                ["organization_id"],
                ["id"],
                ondelete="SET NULL",
            )
            op.create_index("ix_bots_organization_id", "bots", ["organization_id"])
        if "project_id" not in cols:
            op.add_column(
                "bots",
                sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                "fk_bots_project_id_projects",
                "bots",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )
            op.create_index("ix_bots_project_id", "bots", ["project_id"])

        # Backfill organization_id from owner's company_id where possible
        op.execute(
            """
            UPDATE bots AS b
            SET organization_id = u.company_id
            FROM users AS u
            WHERE b.user_id = u.id
              AND b.organization_id IS NULL
              AND u.company_id IS NOT NULL
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "bots" in tables:
        cols = {c["name"] for c in inspector.get_columns("bots")}
        if "project_id" in cols:
            op.drop_constraint("fk_bots_project_id_projects", "bots", type_="foreignkey")
            op.drop_index("ix_bots_project_id", table_name="bots")
            op.drop_column("bots", "project_id")
        if "organization_id" in cols:
            op.drop_constraint("fk_bots_organization_id_companies", "bots", type_="foreignkey")
            op.drop_index("ix_bots_organization_id", table_name="bots")
            op.drop_column("bots", "organization_id")

    if "projects" in tables:
        op.drop_table("projects")

    if "companies" in tables:
        cols = {c["name"] for c in inspector.get_columns("companies")}
        if "slug" in cols:
            op.drop_index("ix_companies_slug", table_name="companies")
            op.drop_column("companies", "slug")

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "is_verified" in cols:
            op.drop_column("users", "is_verified")
        if "is_active" in cols:
            op.drop_column("users", "is_active")
