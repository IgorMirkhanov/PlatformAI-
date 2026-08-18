"""Pydantic schemas for CRM automation rules."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.crm.automation_rule import AutomationTriggerType


class CrmAutomationRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    is_active: bool = True
    trigger_type: AutomationTriggerType
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Rule name must not be empty.")
        return cleaned

    @field_validator("actions")
    @classmethod
    def _actions_must_be_objects(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Each action must be an object.")
            if not str(item.get("type") or "").strip():
                raise ValueError("Each action requires a non-empty 'type'.")
        return value


class CrmAutomationRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    trigger_type: AutomationTriggerType | None = None
    trigger_config: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Rule name must not be empty.")
        return cleaned

    @field_validator("actions")
    @classmethod
    def _actions_must_be_objects(
        cls,
        value: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Each action must be an object.")
            if not str(item.get("type") or "").strip():
                raise ValueError("Each action requires a non-empty 'type'.")
        return value


class CrmAutomationRuleRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    is_active: bool
    trigger_type: AutomationTriggerType
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmAutomationRuleListResponse(BaseModel):
    items: list[CrmAutomationRuleRead]
    total: int
    limit: int
    offset: int
