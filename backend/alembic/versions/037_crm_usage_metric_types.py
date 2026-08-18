"""Alembic: extend usage_metric_type for native CRM analytics events.

Revision ID: 037_crm_usage_metric_types
Revises: 036_crm_api_keys
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "037_crm_usage_metric_types"
down_revision: Union[str, None] = "036_crm_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "DEAL_CREATED",
    "DEAL_WON",
    "DEAL_LOST",
    "TASK_COMPLETED",
)


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction on some PostgreSQL versions.
    with op.get_context().autocommit_block():
        for value in _NEW_VALUES:
            op.execute(
                f"ALTER TYPE usage_metric_type ADD VALUE IF NOT EXISTS '{value}'"
            )


def downgrade() -> None:
    # PostgreSQL cannot drop individual enum values safely; leave as no-op.
    pass
