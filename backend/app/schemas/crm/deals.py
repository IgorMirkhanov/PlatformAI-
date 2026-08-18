"""Pydantic schemas for CRM deals."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.crm.deal import DealStatus


class CrmDealCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    bot_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None
    amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    source: str | None = Field(default=None, max_length=50)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Deal title must not be empty.")
        return cleaned

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.strip().upper()


class CrmDealUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    contact_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    bot_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source: str | None = Field(default=None, max_length=50)
    custom_fields: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Deal title must not be empty.")
        return cleaned

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()


class CrmDealMoveStageRequest(BaseModel):
    stage_id: uuid.UUID


class CrmDealCloseRequest(BaseModel):
    status: DealStatus

    @field_validator("status")
    @classmethod
    def _must_be_terminal(cls, value: DealStatus) -> DealStatus:
        if value not in {DealStatus.WON, DealStatus.LOST}:
            raise ValueError("Close status must be 'won' or 'lost'.")
        return value


class CrmDealStageBrief(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    is_won: bool
    is_lost: bool

    model_config = ConfigDict(from_attributes=True)


class CrmDealContactBrief(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    source: str | None = None
    linked_client_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class CrmDealRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    bot_id: uuid.UUID | None = None
    assigned_user_id: uuid.UUID | None = None
    title: str
    amount: Decimal
    currency: str
    status: DealStatus
    source: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    stage: CrmDealStageBrief | None = None
    contact: CrmDealContactBrief | None = None

    model_config = ConfigDict(from_attributes=True)


class CrmDealListResponse(BaseModel):
    items: list[CrmDealRead]
    total: int
    limit: int
    offset: int
