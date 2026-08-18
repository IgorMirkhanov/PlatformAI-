"""Pydantic schemas for CRM activities, notes, timeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.crm.activity import ActivityType


class CrmActivityCreate(BaseModel):
    type: ActivityType = ActivityType.TASK
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    due_at: datetime | None = None
    assigned_user_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Activity title must not be empty.")
        return cleaned

    @model_validator(mode="after")
    def _require_target(self) -> CrmActivityCreate:
        if self.deal_id is None and self.contact_id is None:
            raise ValueError("Either deal_id or contact_id is required.")
        return self


class CrmActivityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    assigned_user_id: uuid.UUID | None = None
    type: ActivityType | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Activity title must not be empty.")
        return cleaned


class CrmActivityRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    type: ActivityType
    title: str
    description: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_user_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmActivityListResponse(BaseModel):
    items: list[CrmActivityRead]
    total: int
    limit: int
    offset: int


class CrmNoteCreate(BaseModel):
    text: str = Field(..., min_length=1)
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Note text must not be empty.")
        return cleaned

    @model_validator(mode="after")
    def _require_target(self) -> CrmNoteCreate:
        if self.deal_id is None and self.contact_id is None:
            raise ValueError("Either deal_id or contact_id is required.")
        return self


class CrmNoteUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Note text must not be empty.")
        return cleaned


class CrmNoteRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None
    text: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmNoteListResponse(BaseModel):
    items: list[CrmNoteRead]
    total: int
    limit: int
    offset: int


class CrmTimelineEventRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmTimelineListResponse(BaseModel):
    items: list[CrmTimelineEventRead]
    total: int
    limit: int
    offset: int
