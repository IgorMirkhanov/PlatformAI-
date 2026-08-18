"""Pydantic schemas for organization Flow Builder CRUD API (Step 3.3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrgFlowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    is_active: bool = True
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Flow name must not be empty.")
        return cleaned


class OrgFlowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Flow name must not be empty.")
        return cleaned


class OrgFlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    name: str
    is_active: bool
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OrgFlowListResponse(BaseModel):
    items: list[OrgFlowOut]
    total: int


class OrgFlowTestRunRequest(BaseModel):
    message: str = Field(default="Hello", max_length=4000)
    sender_id: str = Field(default="test-user", max_length=255)
    variables: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=128)


class OrgFlowTestRunResponse(BaseModel):
    session_id: str
    flow_id: str
    status: str
    steps_executed: int
    path: list[str]
    variables: dict[str, Any]
    outputs: list[dict[str, Any]]
    error: str | None = None
    is_terminal: bool = False
