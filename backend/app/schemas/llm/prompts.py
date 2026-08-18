"""Pydantic schemas for LLM prompt templates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    content: str = Field(..., min_length=1)
    description: str | None = Field(default=None, max_length=4000)


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    content: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


class PromptTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    version: int
    content: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplateOut]
    total: int


class PromptRenderRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    template_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=128)


class PromptRenderResponse(BaseModel):
    template_id: uuid.UUID
    name: str
    version: int
    rendered: str
