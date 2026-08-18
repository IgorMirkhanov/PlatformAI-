"""LLM Gateway knowledge bases — Postgres-backed chunks + embeddings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class KnowledgeBase(Base):
    """
    Tenant-scoped knowledge base for the LLM Gateway RAG pipeline.

    Distinct from the legacy bot Chroma KB (``KnowledgeBaseDocument`` in core_models).
    Table: ``llm_knowledge_bases``.
    """

    __tablename__ = "llm_knowledge_bases"
    __table_args__ = (
        Index("ix_llm_knowledge_bases_organization_id", "organization_id"),
        Index(
            "uq_llm_knowledge_bases_org_name",
            "organization_id",
            "name",
            unique=True,
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
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

    documents: Mapped[list["KnowledgeDocument"]] = relationship(
        "KnowledgeDocument",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeDocument(Base):
    """
    One text chunk (+ embedding) belonging to an LLM knowledge base.

    ``embedding`` is JSONB ``list[float]`` today (cosine search in app).
    Swap to ``pgvector.Vector`` when the extension is enabled — same column semantics.
    Table: ``llm_knowledge_documents``.
    """

    __tablename__ = "llm_knowledge_documents"
    __table_args__ = (
        Index("ix_llm_knowledge_documents_knowledge_base_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSONB float array — pgvector-ready shape (list[float]).
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False, default=list)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(
        "KnowledgeBase",
        back_populates="documents",
    )
