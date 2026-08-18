"""Add LLM_EXECUTION_FAILURE to diagnostic_error_type enum.

Revision ID: 026_llm_execution_failure
Revises: 025_kb_document_status
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "026_llm_execution_failure"
down_revision: Union[str, None] = "025_kb_document_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL: extend existing enum. IF NOT EXISTS keeps re-runs safe.
    op.execute(
        "ALTER TYPE diagnostic_error_type ADD VALUE IF NOT EXISTS 'LLM_EXECUTION_FAILURE'"
    )


def downgrade() -> None:
    # Postgres cannot easily remove enum values; leave in place.
    pass
