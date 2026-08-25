"""Allow multiple Wazzup channels per org/bot; route by channelId (reference_id).

Drops ``uq_bot_channels_bot_type`` (one row per bot+type) and adds a partial
unique index so each non-null ``reference_id`` maps to exactly one hub row
(e.g. one Wazzup ``channelId`` → one bot).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055_multi_wazzup_channels"
down_revision: Union[str, None] = "054_payment_methods"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bot_channels" not in inspector.get_table_names():
        return

    existing_uniques = {uc["name"] for uc in inspector.get_unique_constraints("bot_channels")}
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("bot_channels")}

    if "uq_bot_channels_bot_type" in existing_uniques:
        op.drop_constraint("uq_bot_channels_bot_type", "bot_channels", type_="unique")

    if "ix_bot_channels_bot_type" not in existing_indexes:
        op.create_index(
            "ix_bot_channels_bot_type",
            "bot_channels",
            ["bot_id", "channel_type"],
            unique=False,
        )

    if "uq_bot_channels_type_reference" not in existing_indexes:
        op.create_index(
            "uq_bot_channels_type_reference",
            "bot_channels",
            ["channel_type", "reference_id"],
            unique=True,
            postgresql_where=sa.text("reference_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "bot_channels" not in inspector.get_table_names():
        return

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("bot_channels")}
    existing_uniques = {uc["name"] for uc in inspector.get_unique_constraints("bot_channels")}

    if "uq_bot_channels_type_reference" in existing_indexes:
        op.drop_index("uq_bot_channels_type_reference", table_name="bot_channels")

    if "ix_bot_channels_bot_type" in existing_indexes:
        op.drop_index("ix_bot_channels_bot_type", table_name="bot_channels")

    if "uq_bot_channels_bot_type" not in existing_uniques:
        op.create_unique_constraint(
            "uq_bot_channels_bot_type",
            "bot_channels",
            ["bot_id", "channel_type"],
        )
