"""Organization-level StripeCustomer + Company stripe mirror

Revision ID: 020_org_stripe_customer
Revises: 019_saas_core
Create Date: 2026-07-20

Creates ``stripe_customers`` (1:1 with organizations), denormalized stripe_*
columns on ``companies``, and backfills from legacy ``stripe_customer_links``
via user.company_id / link.organization_id.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "020_org_stripe_customer"
down_revision: Union[str, None] = "019_saas_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _add_col_if_missing(inspector, table: str, column: sa.Column) -> None:
    if table not in inspector.get_table_names():
        return
    if column.name in _cols(inspector, table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    # Ensure legacy stripe_customer_links exists (SQL 018 may not have run).
    if "stripe_customer_links" not in tables:
        op.create_table(
            "stripe_customer_links",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
            sa.Column("stripe_customer_id", sa.String(128), nullable=False),
            sa.Column("stripe_subscription_id", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("stripe_customer_id", name="uq_stripe_customer_id"),
        )
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())

    if "stripe_customers" not in tables:
        op.create_table(
            "stripe_customers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("stripe_customer_id", sa.String(128), nullable=False),
            sa.Column("stripe_subscription_id", sa.String(128), nullable=True),
            sa.Column("billing_email", sa.String(320), nullable=True),
            sa.Column("status", sa.String(32), nullable=True),
            sa.Column("plan_name", sa.String(32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", name="uq_stripe_customers_org"),
            sa.UniqueConstraint("stripe_customer_id", name="uq_stripe_customers_customer_id"),
        )
        op.create_index("ix_stripe_customers_organization_id", "stripe_customers", ["organization_id"])
        op.create_index("ix_stripe_customers_stripe_subscription_id", "stripe_customers", ["stripe_subscription_id"])

    inspector = sa.inspect(conn)
    _add_col_if_missing(
        inspector,
        "companies",
        sa.Column("stripe_customer_id", sa.String(128), nullable=True),
    )
    _add_col_if_missing(
        inspector,
        "companies",
        sa.Column("stripe_subscription_id", sa.String(128), nullable=True),
    )
    _add_col_if_missing(
        inspector,
        "companies",
        sa.Column("stripe_status", sa.String(32), nullable=True),
    )
    _add_col_if_missing(
        inspector,
        "companies",
        sa.Column("stripe_plan", sa.String(32), nullable=True),
    )

    # Backfill stripe_customers from legacy links (prefer explicit org, else user.company_id).
    if "stripe_customer_links" in tables and "users" in tables:
        op.execute(
            sa.text(
                """
                INSERT INTO stripe_customers (
                    id,
                    organization_id,
                    stripe_customer_id,
                    stripe_subscription_id,
                    billing_email,
                    status,
                    plan_name,
                    created_at,
                    updated_at
                )
                SELECT
                    gen_random_uuid(),
                    org_id,
                    stripe_customer_id,
                    stripe_subscription_id,
                    email,
                    status,
                    NULL,
                    created_at,
                    updated_at
                FROM (
                    SELECT DISTINCT ON (COALESCE(scl.organization_id, u.company_id))
                        COALESCE(scl.organization_id, u.company_id) AS org_id,
                        scl.stripe_customer_id,
                        scl.stripe_subscription_id,
                        u.email AS email,
                        CASE
                            WHEN scl.stripe_subscription_id IS NOT NULL THEN 'active'
                            ELSE 'none'
                        END AS status,
                        COALESCE(scl.created_at, NOW()) AS created_at,
                        COALESCE(scl.updated_at, NOW()) AS updated_at
                    FROM stripe_customer_links scl
                    LEFT JOIN users u ON u.id = scl.user_id
                    WHERE COALESCE(scl.organization_id, u.company_id) IS NOT NULL
                    ORDER BY
                        COALESCE(scl.organization_id, u.company_id),
                        scl.updated_at DESC NULLS LAST
                ) src
                WHERE NOT EXISTS (
                    SELECT 1 FROM stripe_customers sc
                    WHERE sc.organization_id = src.org_id
                       OR sc.stripe_customer_id = src.stripe_customer_id
                )
                """
            )
        )

    # Mirror onto companies (string plan; cast only when enum exists).
    op.execute(
        sa.text(
            """
            UPDATE companies c
            SET
                stripe_customer_id = sc.stripe_customer_id,
                stripe_subscription_id = sc.stripe_subscription_id,
                stripe_status = COALESCE(sc.status, c.stripe_status)
            FROM stripe_customers sc
            WHERE sc.organization_id = c.id
            """
        )
    )
    # Best-effort plan mirror (ignore if column type mismatch).
    try:
        op.execute(
            sa.text(
                """
                UPDATE companies c
                SET stripe_plan = sc.plan_name
                FROM stripe_customers sc
                WHERE sc.organization_id = c.id
                  AND sc.plan_name IS NOT NULL
                """
            )
        )
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = _cols(inspector, "companies")
    for name in ("stripe_plan", "stripe_status", "stripe_subscription_id", "stripe_customer_id"):
        if name in cols:
            op.drop_column("companies", name)
    if "stripe_customers" in inspector.get_table_names():
        op.drop_table("stripe_customers")
