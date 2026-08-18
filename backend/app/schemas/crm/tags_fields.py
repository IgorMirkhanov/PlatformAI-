"""Pydantic schemas for CRM tags and custom field definitions."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.crm.custom_field import CrmEntityType, CrmFieldType

_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class CrmTagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Tag name must not be empty.")
        return cleaned

    @field_validator("color")
    @classmethod
    def _validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not _HEX_COLOR_RE.match(cleaned):
            raise ValueError("Tag color must be a hex value like #FF5733.")
        return cleaned.upper()


class CrmTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Tag name must not be empty.")
        return cleaned

    @field_validator("color")
    @classmethod
    def _validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not _HEX_COLOR_RE.match(cleaned):
            raise ValueError("Tag color must be a hex value like #FF5733.")
        return cleaned.upper()


class CrmTagRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    color: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmTagListResponse(BaseModel):
    items: list[CrmTagRead]
    total: int
    limit: int
    offset: int


class CrmCustomFieldCreate(BaseModel):
    entity_type: CrmEntityType
    field_key: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)
    field_type: CrmFieldType
    options: list[str] | None = None
    is_required: bool = False
    position: int = Field(default=0, ge=0)

    @field_validator("field_key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _FIELD_KEY_RE.match(cleaned):
            raise ValueError(
                "field_key must start with a letter and contain only lowercase letters, digits, underscores."
            )
        return cleaned

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label must not be empty.")
        return cleaned

    @model_validator(mode="after")
    def _options_for_select(self) -> CrmCustomFieldCreate:
        if self.field_type in {CrmFieldType.SELECT, CrmFieldType.MULTISELECT}:
            if not self.options:
                raise ValueError("options are required for select/multiselect fields.")
        return self


class CrmCustomFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    field_type: CrmFieldType | None = None
    options: list[str] | None = None
    is_required: bool | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label must not be empty.")
        return cleaned


class CrmCustomFieldRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    entity_type: CrmEntityType
    field_key: str
    label: str
    field_type: CrmFieldType
    options: list[str] | None = None
    is_required: bool
    position: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrmCustomFieldListResponse(BaseModel):
    items: list[CrmCustomFieldRead]
    total: int
    limit: int
    offset: int
