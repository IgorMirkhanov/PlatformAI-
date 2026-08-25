"""Alembic: BYOK credentials vault + webhook event log + channel routing columns."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "056_byok_credentials_vault"
down_revision: Union[str, None] = "055_multi_wazzup_channels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "credentials" not in tables:
        op.create_table(
            "credentials",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("kind", sa.String(64), nullable=False),
            sa.Column("label", sa.String(255), nullable=True),
            sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
            sa.Column("encryption_iv", sa.LargeBinary(), nullable=False),
            sa.Column("encryption_tag", sa.LargeBinary(), nullable=False),
            sa.Column("key_version", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("oauth_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("oauth_refresh_locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
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
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "organization_id", "kind", "label", name="uq_credentials_org_kind_label"
            ),
        )
        op.create_index("ix_credentials_organization_id", "credentials", ["organization_id"])
        op.create_index("ix_credentials_kind", "credentials", ["kind"])
        op.execute(
            sa.text(
                "CREATE INDEX idx_credentials_oauth_refresh ON credentials (oauth_expires_at) "
                "WHERE kind IN ('crm_amocrm', 'crm_bitrix24') AND status = 'active'"
            )
        )

    if "webhook_event_log" not in tables:
        op.create_table(
            "webhook_event_log",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("reference_id", sa.String(255), nullable=False),
            sa.Column("external_message_id", sa.String(255), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column(
                "processed_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("unmatched", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_webhook_event_log_provider", "webhook_event_log", ["provider"])
        op.create_unique_constraint(
            "uq_webhook_event_log_provider_ref_msg",
            "webhook_event_log",
            ["provider", "reference_id", "external_message_id"],
        )

    if "bot_channels" in tables:
        cols = {c["name"] for c in inspector.get_columns("bot_channels")}
        if "organization_id" not in cols:
            op.add_column(
                "bot_channels",
                sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.execute(
                sa.text(
                    "UPDATE bot_channels AS bc SET organization_id = b.organization_id "
                    "FROM bots AS b WHERE b.id = bc.bot_id"
                )
            )
            op.create_index("ix_bot_channels_organization_id", "bot_channels", ["organization_id"])
        if "credential_id" not in cols:
            op.add_column(
                "bot_channels",
                sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                "fk_bot_channels_credential_id",
                "bot_channels",
                "credentials",
                ["credential_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "webhook_secret" not in cols:
            op.add_column(
                "bot_channels", sa.Column("webhook_secret", sa.String(255), nullable=True)
            )
            op.execute(
                sa.text(
                    "UPDATE bot_channels SET webhook_secret = COALESCE("
                    "meta_data->>'webhook_secret_token', meta_data->>'webhook_secret'"
                    ") WHERE webhook_secret IS NULL"
                )
            )

    if "bots" in tables:
        bot_cols = {c["name"] for c in inspector.get_columns("bots")}
        if "ai_integration_id" not in bot_cols:
            op.add_column(
                "bots",
                sa.Column("ai_integration_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
        if "crm_integration_id" not in bot_cols:
            op.add_column(
                "bots",
                sa.Column("crm_integration_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
        if "fallback_model_name" not in bot_cols:
            op.add_column("bots", sa.Column("fallback_model_name", sa.String(100), nullable=True))
        if "rag_collection_id" not in bot_cols:
            op.add_column("bots", sa.Column("rag_collection_id", sa.String(255), nullable=True))

    if "integrations" in tables:
        int_cols = {c["name"] for c in inspector.get_columns("integrations")}
        if "credential_id" not in int_cols:
            op.add_column(
                "integrations",
                sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                "fk_integrations_credential_id",
                "integrations",
                "credentials",
                ["credential_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "is_fallback_allowed" not in int_cols:
            op.add_column(
                "integrations",
                sa.Column(
                    "is_fallback_allowed",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )
        if "external_account_id" not in int_cols:
            op.add_column(
                "integrations", sa.Column("external_account_id", sa.String(255), nullable=True)
            )
        if "config_json" not in int_cols:
            op.add_column(
                "integrations",
                sa.Column("config_json", postgresql.JSONB(), nullable=False, server_default="{}"),
            )

    if "crm_deals" in tables:
        deal_cols = {c["name"] for c in inspector.get_columns("crm_deals")}
        if "dedup_key" not in deal_cols:
            op.add_column("crm_deals", sa.Column("dedup_key", sa.String(255), nullable=True))
            op.create_index(
                "uq_crm_deals_org_dedup",
                "crm_deals",
                ["organization_id", "dedup_key"],
                unique=True,
                postgresql_where=sa.text("dedup_key IS NOT NULL"),
            )

    enum_names: set[str] = set()
    try:
        enum_names = {e["name"] for e in inspector.get_enums()}
    except Exception:
        enum_names = set()
    if "hub_channel_type" in enum_names:
        op.execute(sa.text("ALTER TYPE hub_channel_type ADD VALUE IF NOT EXISTS 'greenapi'"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "crm_deals" in tables:
        indexes = {ix["name"] for ix in inspector.get_indexes("crm_deals")}
        if "uq_crm_deals_org_dedup" in indexes:
            op.drop_index("uq_crm_deals_org_dedup", table_name="crm_deals")
        cols = {c["name"] for c in inspector.get_columns("crm_deals")}
        if "dedup_key" in cols:
            op.drop_column("crm_deals", "dedup_key")
    if "webhook_event_log" in tables:
        op.drop_table("webhook_event_log")
    if "credentials" in tables:
        op.drop_table("credentials")
