"""Pydantic schemas for CRM API keys and public inbound leads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CrmApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Label must not be empty.")
        return cleaned


class CrmApiKeyRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    label: str
    key_prefix: str
    is_active: bool
    last_used_at: datetime | None = None
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmApiKeyCreated(CrmApiKeyRead):
    """Returned only from POST — includes the raw secret once."""

    api_key: str


class CrmApiKeyListResponse(BaseModel):
    items: list[CrmApiKeyRead]
    total: int
    limit: int
    offset: int


class InboundLeadCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    deal_title: str | None = Field(default=None, max_length=255)
    pipeline_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="api", max_length=50)

    @field_validator("first_name")
    @classmethod
    def _strip_first_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("first_name is required.")
        return cleaned

    @field_validator("phone", "email", "deal_title", "source")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _require_phone_or_email(self) -> InboundLeadCreate:
        if not self.phone and not self.email:
            raise ValueError("Either phone or email is required.")
        return self


class InboundLeadResponse(BaseModel):
    contact_id: uuid.UUID
    deal_id: uuid.UUID
    organization_id: uuid.UUID
    contact_created: bool
    deal_title: str
