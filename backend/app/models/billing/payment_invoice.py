"""Payment invoices — checkout sessions from Stripe / YooKassa / manual."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.core_models import Company


class PaymentProvider(str, enum.Enum):
    STRIPE = "stripe"
    YOOKASSA = "yookassa"
    MANUAL = "manual"


class PaymentInvoiceStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class PaymentItemType(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    TOPUP = "topup"


class PaymentInvoice(Base):
    __tablename__ = "payment_invoices"
    __table_args__ = (
        Index("ix_payment_invoices_org_id", "organization_id"),
        Index("uq_payment_invoices_idempotency_key", "idempotency_key", unique=True),
        Index(
            "uq_payment_invoices_provider_external",
            "provider",
            "external_id",
            unique=True,
            postgresql_where="external_id IS NOT NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    tokens_allocated: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[PaymentInvoiceStatus] = mapped_column(
        Enum(
            PaymentInvoiceStatus,
            name="payment_invoice_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=PaymentInvoiceStatus.PENDING,
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, default="topup")
    package_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
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

    organization: Mapped["Company"] = relationship("Company", lazy="selectin")
