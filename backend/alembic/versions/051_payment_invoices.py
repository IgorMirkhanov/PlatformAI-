"""Revision ID: 051_payment_invoices
Revises: 050_admin_audit_metadata
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "051_payment_invoices"
down_revision: Union[str, None] = "050_admin_audit_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

payment_status = postgresql.ENUM(
    "PENDING",
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
    name="payment_invoice_status",
    create_type=False,
)
org_sub_status = postgresql.ENUM(
    "ACTIVE",
    "PAST_DUE",
    "CANCELED",
    "TRIALING",
    name="organization_subscription_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    payment_status.create(bind, checkfirst=True)
    org_sub_status.create(bind, checkfirst=True)

    op.create_table(
        "payment_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("tokens_allocated", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            payment_status,
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("item_type", sa.String(length=32), nullable=False, server_default="topup"),
        sa.Column("package_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
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
    op.create_index("ix_payment_invoices_org_id", "payment_invoices", ["organization_id"])
    op.create_index(
        "uq_payment_invoices_idempotency_key",
        "payment_invoices",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_payment_invoices_provider_external",
        "payment_invoices",
        ["provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "organization_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_id", sa.String(length=64), nullable=False, server_default="pro"),
        sa.Column(
            "status",
            org_sub_status,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
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

    op.add_column(
        "credit_transactions",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "credit_transactions",
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("credit_transactions", "invoice_id")
    op.drop_column("credit_transactions", "description")
    op.drop_table("organization_subscriptions")
    op.drop_index("uq_payment_invoices_provider_external", table_name="payment_invoices")
    op.drop_index("uq_payment_invoices_idempotency_key", table_name="payment_invoices")
    op.drop_index("ix_payment_invoices_org_id", table_name="payment_invoices")
    op.drop_table("payment_invoices")
    op.execute("DROP TYPE IF EXISTS organization_subscription_status")
    op.execute("DROP TYPE IF EXISTS payment_invoice_status")
