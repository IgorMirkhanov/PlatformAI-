"""Alembic: new bots default to an active auto-trial subscription.

Does not change existing row values — only the column default for new INSERTs
that omit subscription_active. Create/clone services set the flag explicitly.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "066_bot_auto_trial_default"
down_revision: Union[str, None] = "065_bot_subscription_wallet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bots" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "subscription_active" not in cols:
        return
    op.alter_column(
        "bots",
        "subscription_active",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bots" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("bots")}
    if "subscription_active" not in cols:
        return
    op.alter_column(
        "bots",
        "subscription_active",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )
