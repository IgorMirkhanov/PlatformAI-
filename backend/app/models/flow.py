"""SQLAlchemy models for the visual bot-builder (React Flow graphs)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.core_models import Bot


class Flow(Base):
    """
    Visual conversation flow — organization-scoped (Flow Builder 3.x) and/or bot-owned.

    Graph structure lives in ``graph_snapshot`` as ``{"nodes": [...], "edges": [...]}``.
    Optional ``Node`` / ``Edge`` rows mirror canvas rows for legacy bot-builder paths.
    """

    __tablename__ = "flows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled Flow")
    published_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Compiled React Flow document: {"nodes": [...], "edges": [...], "viewport": {...}}
    graph_snapshot: Mapped[dict[str, Any]] = mapped_column(
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

    bot: Mapped["Bot"] = relationship(back_populates="builder_flows")
    nodes: Mapped[list["Node"]] = relationship(
        back_populates="flow",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Node.canvas_id",
    )
    edges: Mapped[list["Edge"]] = relationship(
        back_populates="flow",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Edge.canvas_id",
    )


class Node(Base):
    """Single React Flow node; coordinates + settings stored as JSONB."""

    __tablename__ = "flow_nodes"
    __table_args__ = (
        UniqueConstraint("flow_id", "canvas_id", name="uq_flow_nodes_flow_canvas"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("flows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stable React Flow node id (string on the canvas).
    canvas_id: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="text_message")

    # {"x": 120.5, "y": 80.0}
    position: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {"x": 0, "y": 0},
        server_default='{"x": 0, "y": 0}',
    )
    # Node-specific settings (prompt, buttons, CRM params, …)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Optional React Flow extras (style, width, measured, …)
    meta: Mapped[dict[str, Any]] = mapped_column(
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

    flow: Mapped["Flow"] = relationship(back_populates="nodes")


class Edge(Base):
    """Directed connection between two canvas nodes."""

    __tablename__ = "flow_edges"
    __table_args__ = (
        UniqueConstraint("flow_id", "canvas_id", name="uq_flow_edges_flow_canvas"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("flows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canvas_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    # Handles, labels, animated flags, markerEnd, etc.
    data: Mapped[dict[str, Any]] = mapped_column(
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

    flow: Mapped["Flow"] = relationship(back_populates="edges")
