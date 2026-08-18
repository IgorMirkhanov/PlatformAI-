"""Native CRM — Contact (person), optionally linked to inbox Client."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.crm.account import CrmAccount
    from app.models.crm.deal import CrmDeal


class CrmContact(Base):
    """
    CRM contact person.

    ``linked_client_id`` is a lazy 1:1 bridge to ``clients`` (inbox end-user).
    Tenant scope is always ``organization_id`` (from ``bots.organization_id``
    at auto-capture time — ``clients`` has no org column of its own).
    """

    __tablename__ = "crm_contacts"
    __table_args__ = (
        UniqueConstraint("linked_client_id", name="uq_crm_contacts_linked_client_id"),
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
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    last_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linked_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        unique=True,
    )
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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

    account: Mapped["CrmAccount | None"] = relationship(
        back_populates="contacts",
        lazy="selectin",
    )
    deals: Mapped[list["CrmDeal"]] = relationship(
        back_populates="contact",
        lazy="selectin",
    )
