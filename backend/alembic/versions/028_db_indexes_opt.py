"""Database indexes for high-traffic admin/tenant query patterns.

Revision ID: 028_db_indexes_opt
Revises: 027_llm_deduction_txn
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "028_db_indexes_opt"
down_revision: Union[str, None] = "027_llm_deduction_txn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LLMUsageLog — tenant time-series + per-bot usage dashboards
    op.create_index(
        "ix_llm_usage_logs_org_id_created_at",
        "llm_usage_logs",
        ["org_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_usage_logs_bot_id_created_at",
        "llm_usage_logs",
        ["bot_id", "created_at"],
        unique=False,
    )

    # Bot — org inventory filtered by active flag
    op.create_index(
        "ix_bots_organization_id_is_active",
        "bots",
        ["organization_id", "is_active"],
        unique=False,
    )

    # AdminAuditLog — chronological browse + action filter
    op.create_index(
        "ix_admin_audit_logs_created_at_action",
        "admin_audit_logs",
        ["created_at", "action"],
        unique=False,
    )

    # BotDiagnosticLog — bot error vault (error_type == diagnostic level)
    op.create_index(
        "ix_bot_diagnostic_logs_bot_id_error_type_created_at",
        "bot_diagnostic_logs",
        ["bot_id", "error_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bot_diagnostic_logs_bot_id_error_type_created_at",
        table_name="bot_diagnostic_logs",
    )
    op.drop_index(
        "ix_admin_audit_logs_created_at_action",
        table_name="admin_audit_logs",
    )
    op.drop_index(
        "ix_bots_organization_id_is_active",
        table_name="bots",
    )
    op.drop_index(
        "ix_llm_usage_logs_bot_id_created_at",
        table_name="llm_usage_logs",
    )
    op.drop_index(
        "ix_llm_usage_logs_org_id_created_at",
        table_name="llm_usage_logs",
    )
