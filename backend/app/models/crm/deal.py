"""Native CRM — Deal (opportunity) model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.crm.account import CrmAccount
    from app.models.crm.contact import CrmContact
    from app.models.crm.pipeline import CrmPipeline
    from app.models.crm.stage import CrmStage
    from app.models.crm.tag import CrmTag


class DealStatus(str, enum.Enum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class CrmDeal(Base):
    """Sales opportunity living on a pipeline stage."""

    __tablename__ = "crm_deals"
    __table_args__ = (
        Index(
            "uq_crm_deals_org_dedup",
            "organization_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL"),
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
        index=True,
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_pipelines.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_stages.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="KZT",
        server_default="KZT",
    )
    status: Mapped[DealStatus] = mapped_column(
        Enum(
            DealStatus,
            name="crm_deal_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=False,
        ),
        nullable=False,
        default=DealStatus.OPEN,
        server_default=DealStatus.OPEN.value,
        index=True,
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
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
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    pipeline: Mapped["CrmPipeline"] = relationship(back_populates="deals", lazy="selectin")
    stage: Mapped["CrmStage"] = relationship(back_populates="deals", lazy="selectin")
    contact: Mapped["CrmContact | None"] = relationship(back_populates="deals", lazy="selectin")
    account: Mapped["CrmAccount | None"] = relationship(back_populates="deals", lazy="selectin")
    tags: Mapped[list["CrmTag"]] = relationship(
        secondary="crm_deal_tags",
        back_populates="deals",
        lazy="selectin",
    )
