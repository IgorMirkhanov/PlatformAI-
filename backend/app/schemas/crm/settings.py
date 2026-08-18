"""Pydantic schemas for CRM organization settings."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class CrmSettingRead(BaseModel):
    organization_id: uuid.UUID
    auto_capture_enabled: bool

    model_config = ConfigDict(from_attributes=True)


class CrmSettingUpdate(BaseModel):
    auto_capture_enabled: bool | None = None
