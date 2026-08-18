import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.core_models import UserRole


class UserBase(BaseModel):
    """Shared user fields."""

    email: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)


class UserCreate(UserBase):
    """Schema for creating a new user."""

    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)
    role: UserRole = UserRole.OWNER


class UserUpdate(BaseModel):
    """Schema for partial user updates."""

    email: str | None = Field(default=None, min_length=1, max_length=255)
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None


class UserRead(UserBase):
    """Schema for returning user data to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    company_id: uuid.UUID
    role: UserRole
    created_at: datetime
