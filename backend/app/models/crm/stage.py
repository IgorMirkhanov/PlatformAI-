"""Native CRM — Stage (pipeline column) model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.crm.deal import CrmDeal
    from app.models.crm.pipeline import CrmPipeline


class CrmStage(Base):
    """
    Stage within a CRM pipeline.

    ``organization_id`` is denormalized so tenant filters never need a join
    through ``crm_pipelines``. At most one ``is_won`` / ``is_lost`` stage
    per pipeline is enforced by partial unique indexes.
    """

    __tablename__ = "crm_stages"
    __table_args__ = (
        Index(
            "uq_crm_stages_pipeline_won",
            "pipeline_id",
            unique=True,
            postgresql_where=text("is_won IS TRUE"),
        ),
        Index(
            "uq_crm_stages_pipeline_lost",
            "pipeline_id",
            unique=True,
            postgresql_where=text("is_lost IS TRUE"),
        ),
        Index("ix_crm_stages_pipeline_id", "pipeline_id"),
        Index("ix_crm_stages_organization_id", "organization_id"),
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
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_won: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_lost: Mapped[bool] = mapped_column(
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

    pipeline: Mapped["CrmPipeline"] = relationship(back_populates="stages")
    deals: Mapped[list["CrmDeal"]] = relationship(back_populates="stage", lazy="selectin")
