"""Add LLM_DEDUCTION billing transaction type.

Revision ID: 027_llm_deduction_txn
Revises: 026_llm_execution_failure
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "027_llm_deduction_txn"
down_revision: Union[str, None] = "026_llm_execution_failure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE billing_transaction_type ADD VALUE IF NOT EXISTS 'LLM_DEDUCTION'"
    )


def downgrade() -> None:
    pass
