"""Alembic: operator notification channels + conversation status."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "059_operator_notifications"
down_revision: Union[str, None] = "058_bot_low_balance_message"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    client_cols = {c["name"] for c in inspector.get_columns("clients")} if "clients" in tables else set()
    if "conversation_status" not in client_cols:
        op.add_column(
            "clients",
            sa.Column(
                "conversation_status",
                sa.String(32),
                nullable=False,
                server_default="active",
            ),
        )

    if "operator_notification_channels" not in tables:
        op.create_table(
            "operator_notification_channels",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("channel_type", sa.String(32), nullable=False),
            sa.Column("target_chat_id", sa.String(255), nullable=False),
            sa.Column("webhook_url", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "organization_id",
                "channel_type",
                "target_chat_id",
                name="uq_operator_notify_org_type_target",
            ),
        )
        op.create_index(
            "ix_operator_notification_channels_organization_id",
            "operator_notification_channels",
            ["organization_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "operator_notification_channels" in tables:
        op.drop_table("operator_notification_channels")
    client_cols = {c["name"] for c in inspector.get_columns("clients")} if "clients" in tables else set()
    if "conversation_status" in client_cols:
        op.drop_column("clients", "conversation_status")
