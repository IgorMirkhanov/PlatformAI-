"""Pydantic schemas for organization SQL DB connections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DbType = Literal["postgresql", "mysql"]


class DbConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    db_type: DbType
    connection_string: str = Field(..., min_length=8, max_length=4000)


class DbConnectionOut(BaseModel):
    """Metadata-only response — never includes plaintext credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    db_type: str
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None = None


class DbConnectionListResponse(BaseModel):
    items: list[DbConnectionOut]
    total: int
