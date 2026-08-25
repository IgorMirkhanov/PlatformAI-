"""Add payment_methods table for saved TipTop Pay tokens."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "054_payment_methods"
down_revision: Union[str, None] = "053_card_deposit_txn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "payment_methods" in inspector.get_table_names():
        return

    op.create_table(
        "payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="tiptop"),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("card_last_four", sa.String(length=4), nullable=True),
        sa.Column("card_type", sa.String(length=32), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
    op.create_index("ix_payment_methods_organization_id", "payment_methods", ["organization_id"])
    op.create_index(
        "uq_payment_methods_org_provider",
        "payment_methods",
        ["organization_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_payment_methods_org_provider", table_name="payment_methods")
    op.drop_index("ix_payment_methods_organization_id", table_name="payment_methods")
    op.drop_table("payment_methods")
