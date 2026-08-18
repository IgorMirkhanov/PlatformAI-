"""Pydantic schemas for CRM outbound webhook subscriptions."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_EVENT_TYPES = frozenset(
    {
        "*",
        "deal.created",
        "deal.updated",
        "deal.closed",
        "contact.created",
    }
)


def _normalize_event_types(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = str(raw or "").strip().lower()
        if not item:
            continue
        if item not in ALLOWED_EVENT_TYPES:
            raise ValueError(
                f"Unsupported event_type '{raw}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EVENT_TYPES))}."
            )
        if item not in seen:
            seen.add(item)
            cleaned.append(item)
    if not cleaned:
        raise ValueError("event_types must contain at least one event.")
    return cleaned


class CrmWebhookSubscriptionCreate(BaseModel):
    target_url: str = Field(..., min_length=8, max_length=1024)
    event_types: list[str] = Field(..., min_length=1)
    secret: str | None = Field(default=None, min_length=16, max_length=255)
    is_active: bool = True

    @field_validator("target_url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("target_url is required.")
        return cleaned

    @field_validator("event_types")
    @classmethod
    def _events(cls, value: list[str]) -> list[str]:
        return _normalize_event_types(value)

    @field_validator("secret")
    @classmethod
    def _strip_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CrmWebhookSubscriptionUpdate(BaseModel):
    target_url: str | None = Field(default=None, min_length=8, max_length=1024)
    event_types: list[str] | None = None
    is_active: bool | None = None
    secret: str | None = Field(default=None, min_length=16, max_length=255)

    @field_validator("target_url")
    @classmethod
    def _strip_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("event_types")
    @classmethod
    def _events(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_event_types(value)

    @field_validator("secret")
    @classmethod
    def _strip_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CrmWebhookSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    target_url: str
    event_types: list[str]
    secret: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CrmWebhookSubscriptionCreated(CrmWebhookSubscriptionRead):
    """Same as read — secret is always returned so partners can verify HMAC."""


class CrmWebhookSubscriptionListResponse(BaseModel):
    items: list[CrmWebhookSubscriptionRead]
    total: int
    limit: int
    offset: int
