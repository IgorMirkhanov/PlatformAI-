"""Add CARD_DEPOSIT billing transaction type."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "053_card_deposit_txn"
down_revision: Union[str, None] = "052_llm_model_price_scale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE billing_transaction_type ADD VALUE IF NOT EXISTS 'CARD_DEPOSIT'"
    )


def downgrade() -> None:
    # PostgreSQL enum values cannot be dropped safely without table rewrite.
    pass
