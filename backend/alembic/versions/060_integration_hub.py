"""Alembic: Integration Hub — platform OAuth apps + tenant connections."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "060_integration_hub"
down_revision: Union[str, None] = "059_operator_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "integration_oauth_apps" not in tables:
        op.create_table(
            "integration_oauth_apps",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("client_id", sa.String(255), nullable=False),
            sa.Column("encrypted_client_secret", sa.Text(), nullable=True),
            sa.Column("redirect_uri", sa.String(512), nullable=True),
            sa.Column("auth_base_url", sa.String(512), nullable=True),
            sa.Column("token_url", sa.String(512), nullable=True),
            sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("provider", name="uq_integration_oauth_apps_provider"),
        )

    if "integration_connections" not in tables:
        op.create_table(
            "integration_connections",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column(
                "status",
                sa.String(24),
                nullable=False,
                server_default="disconnected",
            ),
            sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("external_account_id", sa.String(255), nullable=True),
            sa.Column(
                "config_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("oauth_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_integration_connections_org_provider",
            "integration_connections",
            ["organization_id", "provider"],
        )
        op.create_index(
            "ix_integration_connections_bot_id",
            "integration_connections",
            ["bot_id"],
        )
        op.create_index(
            "idx_integration_connections_oauth_refresh",
            "integration_connections",
            ["oauth_expires_at"],
            postgresql_where=sa.text("status = 'connected' AND oauth_expires_at IS NOT NULL"),
        )

    if hasattr(inspector, "clear_cache"):
        inspector.clear_cache()
    if "integration_connections" in set(inspector.get_table_names()):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("integration_connections")}
        existing_uniques = {
            uc["name"] for uc in inspector.get_unique_constraints("integration_connections")
        }
        if "uq_integration_connections_org_bot_provider" in existing_uniques:
            op.drop_constraint(
                "uq_integration_connections_org_bot_provider",
                "integration_connections",
                type_="unique",
            )
            existing_indexes.discard("uq_integration_connections_org_bot_provider")
        if "uq_integration_connections_org_bot_provider" not in existing_indexes:
            op.create_index(
                "uq_integration_connections_org_bot_provider",
                "integration_connections",
                ["organization_id", "bot_id", "provider"],
                unique=True,
                postgresql_where=sa.text("bot_id IS NOT NULL"),
            )
        if "uq_integration_connections_org_provider" not in existing_indexes:
            op.create_index(
                "uq_integration_connections_org_provider",
                "integration_connections",
                ["organization_id", "provider"],
                unique=True,
                postgresql_where=sa.text("bot_id IS NULL"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "integration_connections" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("integration_connections")}
        for name in (
            "uq_integration_connections_org_provider",
            "uq_integration_connections_org_bot_provider",
            "idx_integration_connections_oauth_refresh",
            "ix_integration_connections_bot_id",
            "ix_integration_connections_org_provider",
        ):
            if name in indexes:
                op.drop_index(name, table_name="integration_connections")
        op.drop_table("integration_connections")
    if "integration_oauth_apps" in tables:
        op.drop_table("integration_oauth_apps")
