"""Alembic: per-bot low-balance messenger copy."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "058_bot_low_balance_message"
down_revision: Union[str, None] = "057_organization_wallets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "low_balance_message" not in cols:
        op.add_column("bots", sa.Column("low_balance_message", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "low_balance_message" in cols:
        op.drop_column("bots", "low_balance_message")
