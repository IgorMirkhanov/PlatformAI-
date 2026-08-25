"""Alembic: token wallet columns + immutable wallet_transactions ledger."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "057_organization_wallets"
down_revision: Union[str, None] = "056_byok_credentials_vault"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRACE_TOKENS = 100_000


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    wallet_cols = {c["name"] for c in inspector.get_columns("organization_wallets")} if "organization_wallets" in tables else set()

    if "balance_tokens" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column("balance_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        )
    if "balance_currency_cents" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column(
                "balance_currency_cents",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )
    if "currency" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        )
    if "low_balance_threshold" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column(
                "low_balance_threshold",
                sa.BigInteger(),
                nullable=False,
                server_default="1000",
            ),
        )
    if "status" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        )
    if "blocked_at" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "grace_period_until" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column("grace_period_until", sa.DateTime(timezone=True), nullable=True),
        )
    if "version" not in wallet_cols:
        op.add_column(
            "organization_wallets",
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        )

    constraints = {
        c["name"] for c in inspector.get_check_constraints("organization_wallets")
    } if "organization_wallets" in tables else set()
    if "ck_organization_wallets_balance_tokens_nonneg" not in constraints:
        op.create_check_constraint(
            "ck_organization_wallets_balance_tokens_nonneg",
            "organization_wallets",
            "balance_tokens >= 0",
        )
    if "ck_organization_wallets_currency_cents_nonneg" not in constraints:
        op.create_check_constraint(
            "ck_organization_wallets_currency_cents_nonneg",
            "organization_wallets",
            "balance_currency_cents >= 0",
        )

    if "wallet_transactions" not in tables:
        op.create_table(
            "wallet_transactions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("tx_type", sa.String(32), nullable=False),
            sa.Column("amount_tokens", sa.BigInteger(), nullable=False),
            sa.Column("balance_after", sa.BigInteger(), nullable=False),
            sa.Column("model_used", sa.String(100), nullable=True),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column(
                "metadata_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["wallet_id"],
                ["organization_wallets.organization_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["conversation_id"], ["clients.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_wallet_transactions_org_idempotency",
            ),
            sa.CheckConstraint("amount_tokens > 0", name="ck_wallet_transactions_amount_positive"),
        )
        op.create_index(
            "idx_wallet_tx_org_created",
            "wallet_transactions",
            ["organization_id", "created_at"],
        )
        op.create_index("idx_wallet_tx_bot", "wallet_transactions", ["bot_id", "created_at"])
        op.create_index("ix_wallet_transactions_organization_id", "wallet_transactions", ["organization_id"])
        op.create_index("ix_wallet_transactions_wallet_id", "wallet_transactions", ["wallet_id"])
        op.create_index("ix_wallet_transactions_bot_id", "wallet_transactions", ["bot_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO organization_wallets (
                organization_id, balance, balance_tokens, status, currency, version
            )
            SELECT c.id, 0, :grace, 'active', 'USD', 0
            FROM companies c
            WHERE NOT EXISTS (
                SELECT 1 FROM organization_wallets w WHERE w.organization_id = c.id
            )
            """
        ).bindparams(grace=_GRACE_TOKENS)
    )
    op.execute(
        sa.text(
            """
            UPDATE organization_wallets
            SET balance_tokens = GREATEST(balance, :grace)
            WHERE COALESCE(balance_tokens, 0) = 0
            """
        ).bindparams(grace=_GRACE_TOKENS)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "wallet_transactions" in tables:
        op.drop_table("wallet_transactions")
    wallet_cols = {c["name"] for c in inspector.get_columns("organization_wallets")} if "organization_wallets" in tables else set()
    constraints = {
        c["name"] for c in inspector.get_check_constraints("organization_wallets")
    } if "organization_wallets" in tables else set()
    if "ck_organization_wallets_balance_tokens_nonneg" in constraints:
        op.drop_constraint("ck_organization_wallets_balance_tokens_nonneg", "organization_wallets", type_="check")
    if "ck_organization_wallets_currency_cents_nonneg" in constraints:
        op.drop_constraint("ck_organization_wallets_currency_cents_nonneg", "organization_wallets", type_="check")
    for col in (
        "version",
        "grace_period_until",
        "blocked_at",
        "status",
        "low_balance_threshold",
        "currency",
        "balance_currency_cents",
        "balance_tokens",
    ):
        if col in wallet_cols:
            op.drop_column("organization_wallets", col)
