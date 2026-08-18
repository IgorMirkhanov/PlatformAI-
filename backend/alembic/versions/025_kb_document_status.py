"""Add knowledge document ingest status / progress / error_message.

Revision ID: 025_kb_document_status
Revises: 024_user_stripe_customer
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025_kb_document_status"
down_revision: Union[str, None] = "024_user_stripe_customer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS = sa.Enum(
    "PENDING",
    "PARSING",
    "INDEXED",
    "FAILED",
    name="knowledge_document_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    _STATUS.create(bind, checkfirst=True)
    op.add_column(
        "knowledge_base_documents",
        sa.Column(
            "status",
            _STATUS,
            nullable=False,
            server_default="INDEXED",
        ),
    )
    op.add_column(
        "knowledge_base_documents",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "knowledge_base_documents",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_base_documents_status",
        "knowledge_base_documents",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_base_documents_status", table_name="knowledge_base_documents")
    op.drop_column("knowledge_base_documents", "error_message")
    op.drop_column("knowledge_base_documents", "progress")
    op.drop_column("knowledge_base_documents", "status")
    bind = op.get_bind()
    _STATUS.drop(bind, checkfirst=True)
