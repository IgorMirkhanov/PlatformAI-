"""Pydantic schemas for LLM Gateway knowledge / RAG."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseOut]
    total: int


class KnowledgeDocumentIngestRequest(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=512)
    text: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None
    chunk_size: int | None = Field(default=None, ge=50, le=8000)
    overlap: int | None = Field(default=None, ge=0, le=2000)


class KnowledgeDocumentIngestResponse(BaseModel):
    knowledge_base_id: uuid.UUID
    file_name: str
    chunks_stored: int
    document_ids: list[uuid.UUID]


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=50)


class KnowledgeSearchHit(BaseModel):
    id: uuid.UUID
    file_name: str
    content: str
    score: float
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    knowledge_base_id: uuid.UUID
    query: str
    hits: list[KnowledgeSearchHit]
