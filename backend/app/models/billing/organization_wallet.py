"""Organization wallet — per-tenant credit balance (minimal units)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.billing.credit_transaction import CreditTransaction
    from app.models.wallet import WalletTransaction


class OrganizationWallet(Base):
    """
    Per-organization wallet.

    ``balance`` — credit ledger (existing billing, integer minimal units).
    ``balance_tokens`` — denormalized token cache; source of truth is ``wallet_transactions``.
    Row-level ``FOR UPDATE`` on this PK isolates tenants (Postgres cannot lock another org's row).
    """

    __tablename__ = "organization_wallets"
    __table_args__ = (
        CheckConstraint("balance_tokens >= 0", name="ck_organization_wallets_balance_tokens_nonneg"),
        CheckConstraint(
            "balance_currency_cents >= 0",
            name="ck_organization_wallets_currency_cents_nonneg",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    balance: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    balance_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    balance_currency_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    low_balance_threshold: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1000, server_default="1000"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_period_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
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

    transactions: Mapped[list[CreditTransaction]] = relationship(
        "CreditTransaction",
        back_populates="wallet",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    token_transactions: Mapped[list["WalletTransaction"]] = relationship(
        "WalletTransaction",
        back_populates="wallet",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="WalletTransaction.wallet_id",
    )
