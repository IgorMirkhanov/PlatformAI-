"""Widen llm_models price scale so sub-cent USD tariffs survive.

Numeric(12, 4) rounded OpenRouter prices such as 0.00015 up to 0.0002;
Numeric(14, 6) stores them verbatim.

Revision ID: 052_llm_model_price_scale
Revises: 051_payment_invoices
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052_llm_model_price_scale"
down_revision: Union[str, None] = "051_payment_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "llm_models",
        "cost_per_1k_input",
        existing_type=sa.Numeric(precision=12, scale=4),
        type_=sa.Numeric(precision=14, scale=6),
        existing_nullable=False,
        existing_server_default="10.0000",
    )
    op.alter_column(
        "llm_models",
        "cost_per_1k_output",
        existing_type=sa.Numeric(precision=12, scale=4),
        type_=sa.Numeric(precision=14, scale=6),
        existing_nullable=False,
        existing_server_default="30.0000",
    )


def downgrade() -> None:
    op.alter_column(
        "llm_models",
        "cost_per_1k_output",
        existing_type=sa.Numeric(precision=14, scale=6),
        type_=sa.Numeric(precision=12, scale=4),
        existing_nullable=False,
        existing_server_default="30.0000",
    )
    op.alter_column(
        "llm_models",
        "cost_per_1k_input",
        existing_type=sa.Numeric(precision=14, scale=6),
        type_=sa.Numeric(precision=12, scale=4),
        existing_nullable=False,
        existing_server_default="10.0000",
    )
