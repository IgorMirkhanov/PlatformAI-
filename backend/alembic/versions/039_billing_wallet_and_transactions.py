"""Alembic: organization wallet + credit ledger.

Revision ID: 039_billing_wallet_and_transactions
Revises: 038_crm_webhook_subscriptions
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "039_billing_wallet_and_transactions"
down_revision: Union[str, None] = "038_crm_webhook_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "organization_wallets" not in tables:
        op.create_table(
            "organization_wallets",
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "balance",
                sa.BigInteger(),
                server_default="0",
                nullable=False,
            ),
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
        )

    if "credit_transactions" not in tables:
        op.create_table(
            "credit_transactions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "wallet_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("organization_wallets.organization_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("amount", sa.BigInteger(), nullable=False),
            sa.Column("transaction_type", sa.String(length=64), nullable=False),
            sa.Column("reference_id", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_credit_transactions_wallet_id",
            "credit_transactions",
            ["wallet_id"],
        )
        op.create_index(
            "uq_credit_transactions_type_reference",
            "credit_transactions",
            ["transaction_type", "reference_id"],
            unique=True,
            postgresql_where=sa.text("reference_id IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index(
        "uq_credit_transactions_type_reference",
        table_name="credit_transactions",
    )
    op.drop_index(
        "ix_credit_transactions_wallet_id",
        table_name="credit_transactions",
    )
    op.drop_table("credit_transactions")
    op.drop_table("organization_wallets")
