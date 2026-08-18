"""Pydantic schemas for CRM accounts and contacts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CrmAccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Account name must not be empty.")
        return cleaned


class CrmAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    custom_fields: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Account name must not be empty.")
        return cleaned


class CrmAccountRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    industry: str | None = None
    website: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmAccountListResponse(BaseModel):
    items: list[CrmAccountRead]
    total: int
    limit: int
    offset: int


class CrmContactCreate(BaseModel):
    first_name: str = Field(default="", max_length=255)
    last_name: str = Field(default="", max_length=255)
    phone: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=50)
    account_id: uuid.UUID | None = None
    linked_client_id: uuid.UUID | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    avatar_url: str | None = Field(default=None, max_length=1024)


class CrmContactUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=50)
    account_id: uuid.UUID | None = None
    linked_client_id: uuid.UUID | None = None
    custom_fields: dict[str, Any] | None = None
    avatar_url: str | None = Field(default=None, max_length=1024)


class CrmContactRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    account_id: uuid.UUID | None = None
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    source: str | None = None
    linked_client_id: uuid.UUID | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmContactListResponse(BaseModel):
    items: list[CrmContactRead]
    total: int
    limit: int
    offset: int
