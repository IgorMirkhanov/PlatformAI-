"""Alembic: store webhook payloads and agent action responses for the hub queue."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "062_hub_queue_payloads"
down_revision: Union[str, None] = "061_integration_hub_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "integration_webhook_events" in inspector.get_table_names():
        if not _has_column(inspector, "integration_webhook_events", "payload_json"):
            op.add_column(
                "integration_webhook_events",
                sa.Column(
                    "payload_json",
                    postgresql.JSONB(astext_type=sa.Text()),
                    nullable=False,
                    server_default=sa.text("'{}'::jsonb"),
                ),
            )
        if not _has_column(inspector, "integration_webhook_events", "processed_at"):
            op.add_column(
                "integration_webhook_events",
                sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            )

    if "integration_agent_actions" in inspector.get_table_names():
        if not _has_column(inspector, "integration_agent_actions", "response_json"):
            op.add_column(
                "integration_agent_actions",
                sa.Column(
                    "response_json",
                    postgresql.JSONB(astext_type=sa.Text()),
                    nullable=False,
                    server_default=sa.text("'{}'::jsonb"),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "integration_agent_actions", "response_json"):
        op.drop_column("integration_agent_actions", "response_json")
    if _has_column(inspector, "integration_webhook_events", "processed_at"):
        op.drop_column("integration_webhook_events", "processed_at")
    if _has_column(inspector, "integration_webhook_events", "payload_json"):
        op.drop_column("integration_webhook_events", "payload_json")
