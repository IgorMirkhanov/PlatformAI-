"""Alembic: webhook DLQ retry_count + next_retry_at."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "063_hub_webhook_dlq_retries"
down_revision: Union[str, None] = "062_hub_queue_payloads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "integration_webhook_events"
    if table not in inspector.get_table_names():
        return
    if not _has_column(inspector, table, "retry_count"):
        op.add_column(
            table,
            sa.Column(
                "retry_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not _has_column(inspector, table, "next_retry_at"):
        op.add_column(
            table,
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "integration_webhook_events"
    if table not in inspector.get_table_names():
        return
    if _has_column(inspector, table, "next_retry_at"):
        op.drop_column(table, "next_retry_at")
    if _has_column(inspector, table, "retry_count"):
        op.drop_column(table, "retry_count")
