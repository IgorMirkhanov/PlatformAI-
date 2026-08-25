"""Alembic: idempotency_key for hub usage → billing bridge."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "064_hub_usage_idempotency"
down_revision: Union[str, None] = "063_hub_webhook_dlq_retries"
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
    table = "integration_usage_events"
    if table not in inspector.get_table_names():
        return
    if not _has_column(inspector, table, "idempotency_key"):
        op.add_column(table, sa.Column("idempotency_key", sa.String(255), nullable=True))
    if not _has_index(inspector, table, "uq_integration_usage_events_org_idempotency"):
        op.create_index(
            "uq_integration_usage_events_org_idempotency",
            table,
            ["organization_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "integration_usage_events"
    if table not in inspector.get_table_names():
        return
    if _has_index(inspector, table, "uq_integration_usage_events_org_idempotency"):
        op.drop_index("uq_integration_usage_events_org_idempotency", table_name=table)
    if _has_column(inspector, table, "idempotency_key"):
        op.drop_column(table, "idempotency_key")
