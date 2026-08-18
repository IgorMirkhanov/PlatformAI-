"""Alembic: dynamic LLM model registry.

Revision ID: 049_llm_models
Revises: 048_organization_api_keys
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "049_llm_models"
down_revision: Union[str, None] = "048_organization_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=False, server_default="128000"),
        sa.Column(
            "cost_per_1k_input",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
            server_default="10.0000",
        ),
        sa.Column(
            "cost_per_1k_output",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
            server_default="30.0000",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "is_system_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.UniqueConstraint("provider", "model_name", name="uq_llm_models_provider_model"),
    )
    op.create_index("ix_llm_models_provider", "llm_models", ["provider"])
    op.create_index("ix_llm_models_model_name", "llm_models", ["model_name"])
    op.create_index("ix_llm_models_is_active", "llm_models", ["is_active"])

    llm_models = sa.table(
        "llm_models",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("provider", sa.String),
        sa.column("model_name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("base_url", sa.String),
        sa.column("context_window", sa.Integer),
        sa.column("cost_per_1k_input", sa.Numeric),
        sa.column("cost_per_1k_output", sa.Numeric),
        sa.column("is_active", sa.Boolean),
        sa.column("is_system_default", sa.Boolean),
    )
    op.bulk_insert(
        llm_models,
        [
            {
                "id": uuid.uuid4(),
                "provider": "openai",
                "model_name": "gpt-4o-mini",
                "display_name": "GPT-4o Mini",
                "base_url": None,
                "context_window": 128_000,
                "cost_per_1k_input": Decimal("5.0000"),
                "cost_per_1k_output": Decimal("20.0000"),
                "is_active": True,
                "is_system_default": True,
            },
            {
                "id": uuid.uuid4(),
                "provider": "openai",
                "model_name": "gpt-4o",
                "display_name": "GPT-4o",
                "base_url": None,
                "context_window": 128_000,
                "cost_per_1k_input": Decimal("50.0000"),
                "cost_per_1k_output": Decimal("150.0000"),
                "is_active": True,
                "is_system_default": False,
            },
            {
                "id": uuid.uuid4(),
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "display_name": "DeepSeek Chat",
                "base_url": None,
                "context_window": 64_000,
                "cost_per_1k_input": Decimal("3.0000"),
                "cost_per_1k_output": Decimal("12.0000"),
                "is_active": True,
                "is_system_default": False,
            },
            {
                "id": uuid.uuid4(),
                "provider": "ollama",
                "model_name": "llama3",
                "display_name": "Llama 3 (Local Ollama)",
                "base_url": "http://localhost:11434/v1",
                "context_window": 8_192,
                "cost_per_1k_input": Decimal("0.0000"),
                "cost_per_1k_output": Decimal("0.0000"),
                "is_active": True,
                "is_system_default": False,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_models_is_active", table_name="llm_models")
    op.drop_index("ix_llm_models_model_name", table_name="llm_models")
    op.drop_index("ix_llm_models_provider", table_name="llm_models")
    op.drop_table("llm_models")
