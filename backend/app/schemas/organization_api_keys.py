"""Schemas for organization LLM API key management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OrganizationApiKeyProviderStatus(BaseModel):
    provider: str
    label: str
    configured: bool
    is_active: bool = False
    masked_key: str | None = None
    updated_at: datetime | None = None


class OrganizationApiKeyListResponse(BaseModel):
    items: list[OrganizationApiKeyProviderStatus]


class OrganizationApiKeyUpsertRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=32)
    api_key: str = Field(min_length=8, max_length=512)
    is_active: bool = True


class OrganizationApiKeyUpsertResponse(BaseModel):
    provider: str
    configured: bool
    masked_key: str | None
    is_active: bool
    message: str = "API key saved."
