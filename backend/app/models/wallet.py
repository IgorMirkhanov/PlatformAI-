"""Organization token wallet + immutable ledger (commercial release spec §1.2)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WalletTxType(str, enum.Enum):
    DEBIT_AI_USAGE = "debit_ai_usage"
    CREDIT_TOPUP = "credit_topup"
    CREDIT_REFUND = "credit_refund"
    DEBIT_ADJUSTMENT = "debit_adjustment"
    CREDIT_ADJUSTMENT = "credit_adjustment"


class WalletStatus(str, enum.Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    GRACE_PERIOD = "grace_period"


DEBIT_TX_TYPES = frozenset(
    {WalletTxType.DEBIT_AI_USAGE.value, WalletTxType.DEBIT_ADJUSTMENT.value}
)


class WalletTransaction(Base):
    """Append-only token ledger. ``organization_wallets.balance_tokens`` is a cache."""

    __tablename__ = "wallet_transactions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_wallet_transactions_org_idempotency",
        ),
        Index("idx_wallet_tx_org_created", "organization_id", "created_at"),
        Index("idx_wallet_tx_bot", "bot_id", "created_at"),
        CheckConstraint("amount_tokens > 0", name="ck_wallet_transactions_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_wallets.organization_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    tx_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wallet: Mapped["OrganizationWallet"] = relationship(  # noqa: F821
        "OrganizationWallet",
        back_populates="token_transactions",
        foreign_keys=[wallet_id],
    )
