"""Alembic: unique billing_transactions.reference_id for idempotent debits.

Revision ID: 047_billing_reference_unique
Revises: 046_db_connections
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047_billing_reference_unique"
down_revision: Union[str, None] = "046_db_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_billing_transactions_reference_id"


def _table_exists(inspector: sa.Inspector, name: str) -> bool:
    return name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "billing_transactions"):
        return

    # Keep the earliest ledger row per reference_id; suffix duplicates so the
    # partial unique index can be applied safely on legacy data.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY reference_id
                        ORDER BY created_at ASC, id ASC
                    ) AS rn
                FROM billing_transactions
                WHERE reference_id IS NOT NULL
                  AND btrim(reference_id) <> ''
            )
            UPDATE billing_transactions AS bt
            SET reference_id = bt.reference_id || ':dedup:' || bt.id::text
            FROM ranked AS r
            WHERE bt.id = r.id
              AND r.rn > 1
            """
        )
    )

    existing = {idx["name"] for idx in inspector.get_indexes("billing_transactions")}
    if _INDEX_NAME not in existing:
        op.create_index(
            _INDEX_NAME,
            "billing_transactions",
            ["reference_id"],
            unique=True,
            postgresql_where=sa.text("reference_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "billing_transactions"):
        return

    existing = {idx["name"] for idx in inspector.get_indexes("billing_transactions")}
    if _INDEX_NAME in existing:
        op.drop_index(_INDEX_NAME, table_name="billing_transactions")
