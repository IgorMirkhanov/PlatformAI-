"""Alembic: per-bot subscription flag and credit wallet."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "065_bot_subscription_wallet"
down_revision: Union[str, None] = "064_hub_usage_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bots" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "subscription_active" not in cols:
        op.add_column(
            "bots",
            sa.Column(
                "subscription_active",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )
        # Keep existing live agents chatting until an admin toggles them.
        op.execute(sa.text("UPDATE bots SET subscription_active = true WHERE deleted_at IS NULL"))
    if "subscription_expires_at" not in cols:
        op.add_column(
            "bots",
            sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "wallet_balance" not in cols:
        op.add_column(
            "bots",
            sa.Column(
                "wallet_balance",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bots" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("bots")}
    for name in ("wallet_balance", "subscription_expires_at", "subscription_active"):
        if name in cols:
            op.drop_column("bots", name)
