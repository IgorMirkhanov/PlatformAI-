"""Alembic: Integration Hub core — providers, token columns, webhook/agent/usage events."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "061_integration_hub_core"
down_revision: Union[str, None] = "060_integration_hub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "integration_providers" not in tables:
        op.create_table(
            "integration_providers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("slug", sa.String(32), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("auth_type", sa.String(24), nullable=False, server_default="oauth2"),
            sa.Column("authorize_url", sa.String(512), nullable=True),
            sa.Column("token_url", sa.String(512), nullable=True),
            sa.Column("revoke_url", sa.String(512), nullable=True),
            sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "capabilities",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
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
            sa.UniqueConstraint("slug", name="uq_integration_providers_slug"),
        )

    inspector.clear_cache() if hasattr(inspector, "clear_cache") else None
    inspector = sa.inspect(bind)

    if "integration_oauth_apps" in inspector.get_table_names() and not _has_column(
        inspector, "integration_oauth_apps", "provider_id"
    ):
        op.add_column(
            "integration_oauth_apps",
            sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_integration_oauth_apps_provider_id",
            "integration_oauth_apps",
            "integration_providers",
            ["provider_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_integration_oauth_apps_provider_id",
            "integration_oauth_apps",
            ["provider_id"],
        )

    if "integration_connections" in inspector.get_table_names():
        for col, spec in (
            ("provider_id", sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True)),
            ("oauth_app_id", sa.Column("oauth_app_id", postgresql.UUID(as_uuid=True), nullable=True)),
            ("encrypted_access_token", sa.Column("encrypted_access_token", sa.Text(), nullable=True)),
            ("encrypted_refresh_token", sa.Column("encrypted_refresh_token", sa.Text(), nullable=True)),
            (
                "last_health_check_at",
                sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
            ),
        ):
            if not _has_column(inspector, "integration_connections", col):
                op.add_column("integration_connections", spec)
        inspector = sa.inspect(bind)
        fks = {fk["name"] for fk in inspector.get_foreign_keys("integration_connections")}
        if "fk_integration_connections_provider_id" not in fks:
            op.create_foreign_key(
                "fk_integration_connections_provider_id",
                "integration_connections",
                "integration_providers",
                ["provider_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "fk_integration_connections_oauth_app_id" not in fks:
            op.create_foreign_key(
                "fk_integration_connections_oauth_app_id",
                "integration_connections",
                "integration_oauth_apps",
                ["oauth_app_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if not _has_index(inspector, "integration_connections", "ix_integration_connections_provider_id"):
            op.create_index(
                "ix_integration_connections_provider_id",
                "integration_connections",
                ["provider_id"],
            )
        if not _has_index(inspector, "integration_connections", "ix_integration_connections_oauth_app_id"):
            op.create_index(
                "ix_integration_connections_oauth_app_id",
                "integration_connections",
                ["oauth_app_id"],
            )
        if not _has_index(inspector, "integration_connections", "idx_integration_connections_health"):
            op.create_index(
                "idx_integration_connections_health",
                "integration_connections",
                ["status"],
                postgresql_where=sa.text("status = 'connected'"),
            )

    tables = set(sa.inspect(bind).get_table_names())
    if "integration_webhook_events" not in tables:
        op.create_table(
            "integration_webhook_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("external_event_id", sa.String(255), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="received"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["connection_id"], ["integration_connections.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "provider",
                "external_event_id",
                name="uq_integration_webhook_events_provider_ext",
            ),
        )
        op.create_index(
            "ix_integration_webhook_events_connection",
            "integration_webhook_events",
            ["connection_id", "created_at"],
        )
        op.create_index(
            "ix_integration_webhook_events_organization_id",
            "integration_webhook_events",
            ["organization_id"],
        )

    if "integration_agent_actions" not in tables:
        op.create_table(
            "integration_agent_actions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="ok"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "request_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_integration_agent_actions_connection_created",
            "integration_agent_actions",
            ["connection_id", "created_at"],
        )
        op.create_index(
            "ix_integration_agent_actions_org_created",
            "integration_agent_actions",
            ["organization_id", "created_at"],
        )

    if "integration_usage_events" not in tables:
        op.create_table(
            "integration_usage_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("metric", sa.String(64), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["connection_id"], ["integration_connections.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "ix_integration_usage_events_org_created",
            "integration_usage_events",
            ["organization_id", "created_at"],
        )
        op.create_index(
            "ix_integration_usage_events_connection_created",
            "integration_usage_events",
            ["connection_id", "created_at"],
        )

    op.execute(
        """
        INSERT INTO integration_providers
            (id, slug, name, auth_type, authorize_url, token_url, revoke_url, scopes, capabilities)
        VALUES
            (gen_random_uuid(), 'amocrm', 'amoCRM', 'oauth2',
             'https://www.amocrm.ru/oauth', NULL, NULL,
             '["crm"]'::jsonb,
             '{"contacts": true, "deals": true, "notes": true}'::jsonb),
            (gen_random_uuid(), 'bitrix24', 'Bitrix24', 'oauth2',
             'https://oauth.bitrix.info/oauth/authorize/',
             'https://oauth.bitrix.info/oauth/token/',
             'https://oauth.bitrix.info/oauth/revoke/',
             '["crm"]'::jsonb,
             '{"contacts": true, "deals": true, "notes": true}'::jsonb),
            (gen_random_uuid(), 'wazzup', 'Wazzup', 'api_key',
             NULL, NULL, NULL, NULL,
             '{"messaging": true}'::jsonb),
            (gen_random_uuid(), 'whatsapp', 'WhatsApp', 'api_key',
             NULL, NULL, NULL, NULL,
             '{"messaging": true}'::jsonb),
            (gen_random_uuid(), 'kaspi_pay', 'Kaspi Pay', 'api_key',
             NULL, NULL, NULL, NULL,
             '{"payments": true}'::jsonb)
        ON CONFLICT (slug) DO NOTHING
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name in (
        "integration_usage_events",
        "integration_agent_actions",
        "integration_webhook_events",
    ):
        if name in tables:
            op.drop_table(name)
    if "integration_connections" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("integration_connections")}
        if "idx_integration_connections_health" in indexes:
            op.drop_index("idx_integration_connections_health", table_name="integration_connections")
        for col in (
            "last_health_check_at",
            "encrypted_refresh_token",
            "encrypted_access_token",
            "oauth_app_id",
            "provider_id",
        ):
            if _has_column(inspector, "integration_connections", col):
                op.drop_column("integration_connections", col)
    if "integration_oauth_apps" in tables and _has_column(inspector, "integration_oauth_apps", "provider_id"):
        op.drop_column("integration_oauth_apps", "provider_id")
    if "integration_providers" in tables:
        op.drop_table("integration_providers")
