"""SaaS metering, Stripe linkage, flow revisions, moderation audit."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UsageMetricType(str, enum.Enum):
    LLM_TOKENS = "LLM_TOKENS"
    MESSAGE_IN = "MESSAGE_IN"
    MESSAGE_OUT = "MESSAGE_OUT"
    BOT_CREATED = "BOT_CREATED"
    CRM_CALL = "CRM_CALL"
    RAG_QUERY = "RAG_QUERY"
    # Native CRM — feeds Org ROI / funnel analytics (non-billable meters)
    DEAL_CREATED = "DEAL_CREATED"
    DEAL_WON = "DEAL_WON"
    DEAL_LOST = "DEAL_LOST"
    TASK_COMPLETED = "TASK_COMPLETED"


class UsageEvent(Base):
    """Immutable usage meter row (feeds billing debit + analytics)."""

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metric_type: Mapped[UsageMetricType] = mapped_column(
        Enum(UsageMetricType, name="usage_metric_type"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KZT", server_default="KZT")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class StripeCustomer(Base):
    """Organization-level Stripe customer (one per tenant)."""

    __tablename__ = "stripe_customers"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_stripe_customers_org"),
        UniqueConstraint("stripe_customer_id", name="uq_stripe_customers_customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    billing_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True, default="none")
    plan_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StripeCustomerLink(Base):
    """Deprecated user-scoped Stripe link (kept for migration / rollback). Prefer StripeCustomer."""

    __tablename__ = "stripe_customer_links"
    __table_args__ = (UniqueConstraint("stripe_customer_id", name="uq_stripe_customer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BotFlowRevision(Base):
    """Immutable published graph snapshot for versioning / rollback."""

    __tablename__ = "bot_flow_revisions"
    __table_args__ = (UniqueConstraint("bot_id", "version", name="uq_bot_flow_revision_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled")
    graph_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# Spec alias — BotFlowVersion == immutable publish snapshot.
BotFlowVersion = BotFlowRevision


class ModerationAction(str, enum.Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REDACT = "REDACT"


class ModerationEvent(Base):
    """Audit trail for AI guardrails decisions."""

    __tablename__ = "moderation_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="inbound")
    action: Mapped[ModerationAction] = mapped_column(
        Enum(ModerationAction, name="moderation_action"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    sample: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProcessedStripeEvent(Base):
    """Idempotency ledger for Stripe webhooks."""

    __tablename__ = "processed_stripe_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
