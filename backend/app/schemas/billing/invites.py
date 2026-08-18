"""Pydantic schemas for organization email invites."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.core_models import UserRole

_INVITE_ROLES = frozenset(
    {
        UserRole.ADMIN.value,
        UserRole.OPERATOR.value,
        UserRole.MEMBER.value,
        UserRole.PROMPT_ENGINEER.value,
    }
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OrganizationInviteCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(..., min_length=2, max_length=32)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _EMAIL_RE.match(cleaned):
            raise ValueError("Invalid email address.")
        return cleaned

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned == UserRole.OWNER.value:
            raise ValueError("Cannot invite a user as OWNER via email invite.")
        if cleaned not in _INVITE_ROLES:
            raise ValueError(
                f"Unsupported invite role '{value}'. "
                f"Allowed: {', '.join(sorted(_INVITE_ROLES))}."
            )
        return cleaned


class OrganizationInviteCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    token: str
    created_at: datetime


class OrganizationInviteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    is_accepted: bool
    created_at: datetime
    invited_by_id: uuid.UUID | None = None


class OrganizationInviteListResponse(BaseModel):
    items: list[OrganizationInviteRead]
    total: int


class AcceptOrganizationInviteRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=256)

    @field_validator("token")
    @classmethod
    def _strip_token(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("token is required.")
        return cleaned


class AcceptOrganizationInviteResponse(BaseModel):
    organization_id: uuid.UUID
    role: str
    membership_id: uuid.UUID
    email: str
