"""Alembic: omnichannel message history log.

Revision ID: 043_omnichannel_messages
Revises: 042_knowledge_base
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "043_omnichannel_messages"
down_revision: Union[str, None] = "042_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "omnichannel_message_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("sender_recipient", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_omnichannel_message_logs_organization_id",
        "omnichannel_message_logs",
        ["organization_id"],
    )
    op.create_index(
        "ix_omnichannel_message_logs_org_channel_contact",
        "omnichannel_message_logs",
        ["organization_id", "channel", "sender_recipient"],
    )
    op.create_index(
        "ix_omnichannel_message_logs_created_at",
        "omnichannel_message_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_omnichannel_message_logs_created_at",
        table_name="omnichannel_message_logs",
    )
    op.drop_index(
        "ix_omnichannel_message_logs_org_channel_contact",
        table_name="omnichannel_message_logs",
    )
    op.drop_index(
        "ix_omnichannel_message_logs_organization_id",
        table_name="omnichannel_message_logs",
    )
    op.drop_table("omnichannel_message_logs")
