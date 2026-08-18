"""Alembic: LLM Gateway knowledge bases + document chunks with embeddings.

Revision ID: 042_knowledge_base
Revises: 041_prompt_templates
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "042_knowledge_base"
down_revision: Union[str, None] = "041_prompt_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
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
    op.create_index(
        "ix_llm_knowledge_bases_organization_id",
        "llm_knowledge_bases",
        ["organization_id"],
    )
    op.create_index(
        "uq_llm_knowledge_bases_org_name",
        "llm_knowledge_bases",
        ["organization_id", "name"],
        unique=True,
    )

    op.create_table(
        "llm_knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("chunk_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_llm_knowledge_documents_knowledge_base_id",
        "llm_knowledge_documents",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_knowledge_documents_knowledge_base_id",
        table_name="llm_knowledge_documents",
    )
    op.drop_table("llm_knowledge_documents")
    op.drop_index("uq_llm_knowledge_bases_org_name", table_name="llm_knowledge_bases")
    op.drop_index(
        "ix_llm_knowledge_bases_organization_id",
        table_name="llm_knowledge_bases",
    )
    op.drop_table("llm_knowledge_bases")
