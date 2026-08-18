"""Auth schemas — JWT / OAuth2 password flow."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    company_id: uuid.UUID | None = None
    role: str | None = None


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)
    company_name: str = Field(default="My Organization", max_length=255)


class UserRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    company_name: str
    company_id: uuid.UUID
    role: str
    is_superadmin: bool
    is_support: bool = False
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginJSONRequest(BaseModel):
    """JSON login alternative to OAuth2 form (Swagger + SPA)."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPairResponse(TokenResponse):
    """Access + refresh token pair."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Optional refresh token to revoke on logout (SPA should send it)."""

    refresh_token: str | None = Field(default=None, min_length=16, max_length=512)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)


class OAuthStubCallbackRequest(BaseModel):
    """Social login stub — accepts a provider account id as if OAuth succeeded."""

    provider: str = Field(pattern="^(google|github)$")
    provider_account_id: str = Field(min_length=1, max_length=255)
    email: EmailStr
    full_name: str = Field(default="", max_length=255)
