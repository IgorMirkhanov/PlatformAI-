"""Pydantic schemas for dynamic LLM model registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMModelBase(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model_name: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=255)
    base_url: str | None = Field(default=None, max_length=512)
    context_window: int = Field(default=128_000, ge=512, le=2_000_000)
    cost_per_1k_input: Decimal = Field(default=Decimal("10.0000"), ge=0)
    cost_per_1k_output: Decimal = Field(default=Decimal("30.0000"), ge=0)
    is_active: bool = True
    is_system_default: bool = False

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return (value or "").strip().lower()

    @field_validator("model_name")
    @classmethod
    def normalize_model_name_field(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class LLMModelCreate(LLMModelBase):
    pass


class LLMModelUpdate(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, max_length=512)
    context_window: int | None = Field(default=None, ge=512, le=2_000_000)
    cost_per_1k_input: Decimal | None = Field(default=None, ge=0)
    cost_per_1k_output: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None
    is_system_default: bool | None = None


class LLMModelRead(LLMModelBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class LLMModelListResponse(BaseModel):
    items: list[LLMModelRead]
    total: int


class LLMModelTestConnectionRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model_name: str = Field(..., min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    model_id: uuid.UUID | None = None


class LLMModelTestConnectionResponse(BaseModel):
    ok: bool
    latency_ms: float
    model: str
    provider: str
    message: str
    sample_reply: str | None = None
