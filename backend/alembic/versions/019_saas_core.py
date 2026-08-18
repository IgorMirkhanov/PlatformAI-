"""saas soft-delete, auth tokens, integrations, botflow nodes/edges

Revision ID: 019_saas_core
Revises: 017_tenancy_auth
Create Date: 2026-07-16

Idempotent additive migration for SaaS backend core.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019_saas_core"
down_revision: Union[str, None] = "017_tenancy_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _add_col_if_missing(inspector, table: str, column: sa.Column) -> None:
    if table not in inspector.get_table_names():
        return
    if column.name in _cols(inspector, table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    # --- soft delete / timestamps on core tables ---
    _add_col_if_missing(
        inspector,
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    _add_col_if_missing(
        inspector,
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    for table in ("companies", "projects", "knowledge_base_documents"):
        _add_col_if_missing(
            inspector,
            table,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "knowledge_base_documents" in tables:
        _add_col_if_missing(
            inspector,
            "knowledge_base_documents",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    if "bots" in tables:
        for col in (
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
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        ):
            _add_col_if_missing(inspector, "bots", col)

    if "bot_flows" in tables:
        for col in (
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "nodes",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "edges",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
        ):
            _add_col_if_missing(inspector, "bot_flows", col)

        # Backfill nodes/edges from graph_data when empty
        op.execute(
            sa.text(
                """
                UPDATE bot_flows
                SET
                  nodes = COALESCE(graph_data->'nodes', '[]'::jsonb),
                  edges = COALESCE(graph_data->'edges', '[]'::jsonb)
                WHERE (nodes = '[]'::jsonb OR nodes IS NULL)
                   OR (edges = '[]'::jsonb OR edges IS NULL)
                """
            )
        )

    # --- auth support tables ---
    if "refresh_tokens" not in tables:
        op.create_table(
            "refresh_tokens",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column("ip_address", sa.String(64), nullable=True),
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
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
        )

    if "oauth_accounts" not in tables:
        op.create_table(
            "oauth_accounts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("provider_account_id", sa.String(255), nullable=False),
            sa.Column("access_token", sa.Text(), nullable=True),
            sa.Column("refresh_token", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_profile", sa.Text(), nullable=True),
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
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "provider", "provider_account_id", name="uq_oauth_provider_account"
            ),
        )
        op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])

    # --- integrations ---
    if "integrations" not in tables:
        integration_provider = postgresql.ENUM(
            "whatsapp",
            "telegram",
            "instagram",
            "vkontakte",
            "web_widget",
            "custom",
            name="integration_provider",
            create_type=False,
        )
        integration_status = postgresql.ENUM(
            "disconnected",
            "connecting",
            "connected",
            "error",
            name="integration_status",
            create_type=False,
        )
        integration_provider.create(conn, checkfirst=True)
        integration_status.create(conn, checkfirst=True)

        op.create_table(
            "integrations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "provider",
                postgresql.ENUM(
                    "whatsapp",
                    "telegram",
                    "instagram",
                    "vkontakte",
                    "web_widget",
                    "custom",
                    name="integration_provider",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "disconnected",
                    "connecting",
                    "connected",
                    "error",
                    name="integration_status",
                    create_type=False,
                ),
                nullable=False,
                server_default="disconnected",
            ),
            sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "credentials",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("last_error", sa.Text(), nullable=True),
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
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "organization_id",
                "bot_id",
                "provider",
                name="uq_integration_org_bot_provider",
            ),
        )
        op.create_index(
            "ix_integrations_organization_id", "integrations", ["organization_id"]
        )
        op.create_index("ix_integrations_bot_id", "integrations", ["bot_id"])
        op.create_index("ix_integrations_deleted_at", "integrations", ["deleted_at"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "integrations" in tables:
        op.drop_table("integrations")
    if "oauth_accounts" in tables:
        op.drop_table("oauth_accounts")
    if "password_reset_tokens" in tables:
        op.drop_table("password_reset_tokens")
    if "refresh_tokens" in tables:
        op.drop_table("refresh_tokens")

    # Soft-delete columns are left in place on downgrade to avoid data loss.
