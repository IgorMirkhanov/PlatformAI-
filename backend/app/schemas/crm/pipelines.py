"""Pydantic schemas for native CRM pipelines / stages."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CrmStageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    position: int | None = None
    color: str | None = Field(default=None, max_length=32)
    is_won: bool = False
    is_lost: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Stage name must not be empty.")
        return cleaned

    @field_validator("color")
    @classmethod
    def _normalize_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CrmStageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    position: int | None = None
    color: str | None = Field(default=None, max_length=32)
    is_won: bool | None = None
    is_lost: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Stage name must not be empty.")
        return cleaned


class CrmStageRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    pipeline_id: uuid.UUID
    name: str
    position: int
    color: str | None = None
    is_won: bool
    is_lost: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmPipelineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    position: int | None = None
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Pipeline name must not be empty.")
        return cleaned


class CrmPipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    position: int | None = None
    is_default: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Pipeline name must not be empty.")
        return cleaned


class CrmPipelineRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    position: int
    is_default: bool
    stages: list[CrmStageRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmStageReorderItem(BaseModel):
    id: uuid.UUID
    position: int = Field(..., ge=0)


class CrmStageReorderRequest(BaseModel):
    stages: list[CrmStageReorderItem] = Field(..., min_length=1)
