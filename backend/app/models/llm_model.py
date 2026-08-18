"""Dynamic LLM model registry (provider, pricing, custom endpoints)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LLMModel(Base):
    """
    Platform-wide catalog of chat models available in Flow Builder and Gateway.

    Custom OpenAI-compatible endpoints (Ollama, vLLM, OpenRouter) set ``provider``
    to ``custom_openai`` (or vendor id) and optional ``base_url``.
    """

    __tablename__ = "llm_models"
    __table_args__ = (
        UniqueConstraint("provider", "model_name", name="uq_llm_models_provider_model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    context_window: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=128_000,
        server_default="128000",
    )
    # scale=6 keeps sub-cent USD tariffs (OpenRouter 0.00015 / 1k) exact.
    cost_per_1k_input: Mapped[Decimal] = mapped_column(
        Numeric(precision=14, scale=6),
        nullable=False,
        default=Decimal("10.0000"),
        server_default="10.0000",
    )
    cost_per_1k_output: Mapped[Decimal] = mapped_column(
        Numeric(precision=14, scale=6),
        nullable=False,
        default=Decimal("30.0000"),
        server_default="30.0000",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    is_system_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
