"""Add users.is_support for SUPPORT platform role."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022_user_is_support"
down_revision = "021_admin_audit_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_support",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_support")
