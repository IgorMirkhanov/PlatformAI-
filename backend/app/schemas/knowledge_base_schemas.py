from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeBaseUploadRequest(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    file_name: str = Field(default="pasted-text.txt", min_length=1, max_length=512)


class KnowledgeBaseUploadResponse(BaseModel):
    knowledge_base_id: str
    document_id: uuid.UUID
    file_name: str
    character_count: int
    chunks_stored: int
    message: str = "Document processed and stored successfully."


class KnowledgeBaseDocumentItem(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    file_name: str
    source_type: Literal["file", "text", "web", "google_drive"]
    format: str | None = None
    character_count: int
    chunk_count: int
    is_context_active: bool = True
    status: Literal["PENDING", "PARSING", "INDEXED", "FAILED"] = "INDEXED"
    progress: int = 100
    error_message: str | None = None
    created_at: datetime


class KnowledgeTestSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=20)


class KnowledgeTestSearchChunk(BaseModel):
    text: str
    similarity_score: float
    cosine_distance: float
    match_percent: int
    file_name: str | None = None
    document_id: str | None = None
    page_number: int | None = None
    section: str | None = None
    chunk_index: int | None = None


class KnowledgeTestSearchResponse(BaseModel):
    kb_id: str
    query: str
    top_k: int
    chunks: list[KnowledgeTestSearchChunk]
    total: int


class KnowledgeAsyncUploadResponse(BaseModel):
    task_id: str
    document_id: uuid.UUID
    bot_id: uuid.UUID
    kb_id: str
    status: Literal["PENDING", "PARSING", "INDEXED", "FAILED"] = "PENDING"
    message: str = "Document queued for background indexing."


class KnowledgeBaseChunkItem(BaseModel):
    chunk_index: int
    text: str
    similarity_weight: float


class KnowledgeBaseChunksResponse(BaseModel):
    bot_id: uuid.UUID
    document_id: uuid.UUID
    file_name: str
    chunks: list[KnowledgeBaseChunkItem]
    total: int


class BotKnowledgeToggleRequest(BaseModel):
    document_id: uuid.UUID
    is_context_active: bool


class BotKnowledgeDocumentToggleRequest(BaseModel):
    """Body for path-param toggle: PATCH .../knowledge/{document_id}/toggle."""

    is_context_active: bool


class BotKnowledgeToggleResponse(BaseModel):
    bot_id: uuid.UUID
    document_id: uuid.UUID
    is_context_active: bool
    message: str = "Document search visibility updated."


class BotKnowledgeUploadResponse(KnowledgeBaseUploadResponse):
    source_type: Literal["file", "text", "web", "google_drive"] = "file"


class GoogleSyncRequest(BaseModel):
    google_url: str = Field(min_length=8, max_length=2048)


class GoogleSyncAcceptedResponse(BaseModel):
    bot_id: uuid.UUID
    document_id: uuid.UUID
    google_url: str
    format: str = "Google Drive"
    status: Literal["accepted"] = "accepted"
    message: str = "Синхронизация с Google Диском запущена в фоновом режиме"


class BotKnowledgeReindexRequest(BaseModel):
    crawl_depth: int = Field(default=1, ge=1, le=5)


class BotKnowledgeReindexResponse(BaseModel):
    bot_id: uuid.UUID
    document_id: uuid.UUID
    file_name: str
    character_count: int
    chunks_stored: int
    message: str = "Document reindexed successfully."


class KnowledgeBaseDocumentContextUpdate(BaseModel):
    is_context_active: bool


class KnowledgeBaseDocumentContextResponse(BaseModel):
    bot_id: uuid.UUID
    document_id: uuid.UUID
    is_context_active: bool
    message: str = "Document context association updated."


class KnowledgeBaseDocumentListResponse(BaseModel):
    bot_id: uuid.UUID
    knowledge_base_id: str
    documents: list[KnowledgeBaseDocumentItem]
    total: int


class KnowledgeBaseDeleteResponse(BaseModel):
    bot_id: uuid.UUID
    document_id: uuid.UUID
    deleted: bool
    vectors_removed: int
    message: str = "Document and associated vectors removed successfully."
