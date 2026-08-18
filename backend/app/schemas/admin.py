"""Admin Panel Pydantic schemas (dashboard, CRM, impersonation, audit)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.core_models import UserRole


class ImpersonateByEmailRequest(BaseModel):
    email: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        description="Client account email (legacy field name)",
    )
    user_email: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        description="Client account email to impersonate",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Admin password re-auth (step-up) required before impersonation",
    )

    @model_validator(mode="after")
    def _require_email(self) -> ImpersonateByEmailRequest:
        resolved = (self.user_email or self.email or "").strip().lower()
        if not resolved or "@" not in resolved:
            raise ValueError("user_email or email is required.")
        self.user_email = resolved
        self.email = resolved
        return self


class AdminUserBotSummary(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool = True


class AdminUserSearchItem(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    organization_id: uuid.UUID
    organization_name: str
    plan_name: str
    credit_balance: float
    credit_balance_units: int
    active_bots: int
    bots: list[AdminUserBotSummary] = Field(default_factory=list)
    last_activity_at: datetime | None = None
    is_active: bool = True
    is_superadmin: bool = False
    is_support: bool = False
    platform_role: str = "USER"


class AdminUserSearchResponse(BaseModel):
    items: list[AdminUserSearchItem]
    total: int
    query: str
    page: int = 1
    page_size: int = 25
    total_pages: int = 1


class ImpersonationConfirmRequest(BaseModel):
    """Password step-up for impersonation routes that take the target in the path."""

    password: str = Field(..., min_length=1, max_length=256)


class ImpersonateByUserIdRequest(BaseModel):
    user_id: uuid.UUID
    password: str = Field(..., min_length=1, max_length=256)


class ImpersonationEndRequest(BaseModel):
    target_user_id: uuid.UUID | None = None
    email: str | None = None

    @field_validator("email")
    @classmethod
    def _normalize_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None


class ImpersonationResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    organization_id: uuid.UUID
    organization_name: str
    impersonated_user_id: uuid.UUID
    impersonated_user_email: str
    impersonated_user_name: str = ""
    impersonated_user_role: str = "OWNER"
    impersonated_by: uuid.UUID
    expires_at: datetime
    headers: dict[str, str] = Field(default_factory=dict)
    message: str = "Impersonation token issued."


class ImpersonationEndResponse(BaseModel):
    success: bool = True
    message: str = "Impersonation ended and audit logged."


class AdminClientItem(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    company_name: str
    company_id: uuid.UUID
    role: UserRole
    platform_role: str = "USER"
    is_superadmin: bool = False
    is_support: bool = False
    is_active: bool = True
    wallet_balance: float = 0.0
    created_at: datetime


class AdminPlatformRoleUpdate(BaseModel):
    platform_role: str = Field(..., min_length=3, max_length=32)

    @field_validator("platform_role")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        raw = value.strip().upper()
        aliases = {
            "USER": "USER",
            "ADMIN": "ADMIN",
            "SUPPORT": "ADMIN",
            "SUPERADMIN": "SUPERADMIN",
            "SUPER_ADMIN": "SUPERADMIN",
            "SUPERUSER": "SUPERADMIN",
        }
        mapped = aliases.get(raw)
        if mapped is None:
            raise ValueError("platform_role must be USER, ADMIN, or SUPERADMIN.")
        return mapped


class AdminPlatformRoleUpdateResponse(BaseModel):
    id: uuid.UUID
    email: str
    platform_role: str
    is_superadmin: bool
    is_support: bool
    message: str = "Platform role updated."


class AdminClientListResponse(BaseModel):
    clients: list[AdminClientItem]
    total: int
    query: str = ""


class AdminOrganizationItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str | None = None
    owner_user_id: uuid.UUID
    owner_email: str
    wallet_balance: float = 0.0
    currency: str = "KZT"
    stripe_status: str = "none"
    stripe_plan: str | None = None
    active_bots: int = 0
    is_suspended: bool = False
    total_llm_spent: float = 0.0
    created_at: datetime


class AdminOrganizationListResponse(BaseModel):
    organizations: list[AdminOrganizationItem]
    total: int


class AdminOrganizationSuspendResponse(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    is_suspended: bool
    message: str = "Organization suspension updated."


class AdminBalanceAdjustRequest(BaseModel):
    amount_delta: float = Field(..., description="Positive to credit, negative to debit")
    reason: str = Field(..., min_length=1, max_length=1024)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Reason is required.")
        return cleaned

    @field_validator("amount_delta")
    @classmethod
    def _nonzero_delta(cls, value: float) -> float:
        if value == 0:
            raise ValueError("amount_delta must be non-zero.")
        return value


class AdminBalanceAdjustResponse(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    owner_user_id: uuid.UUID
    previous_balance: float
    amount_delta: float
    new_balance: float
    currency: str = "KZT"
    transaction_id: uuid.UUID
    message: str = "Balance updated."


class AdminTransactionItem(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    user_id: uuid.UUID
    user_email: str
    amount: float
    currency: str
    status: str
    status_raw: str
    transaction_type: str
    description: str
    created_at: datetime


class AdminTransactionListResponse(BaseModel):
    transactions: list[AdminTransactionItem]
    total: int


class AdminLogItem(BaseModel):
    id: uuid.UUID
    level: str
    action: str
    message: str
    created_at: datetime
    bot_id: uuid.UUID | None = None


class AdminLogListResponse(BaseModel):
    logs: list[AdminLogItem]
    total: int


class AdminStatsResponse(BaseModel):
    total_organizations: int
    total_active_bots: int
    total_revenue: float
    total_llm_cost: float = 0.0
    total_tokens: int = 0
    error_log_count: int = 0
    currency: str = "KZT"


class AdminBotItem(BaseModel):
    id: uuid.UUID
    name: str
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    owner_email: str | None = None
    is_active: bool
    created_at: datetime


class AdminBotListResponse(BaseModel):
    bots: list[AdminBotItem]
    total: int


class AdminAuditItem(BaseModel):
    id: uuid.UUID
    admin_id: uuid.UUID
    target_user_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    action: str
    details: str | None = None
    ip_address: str | None = None
    created_at: datetime


class AdminAuditListResponse(BaseModel):
    entries: list[AdminAuditItem]
    total: int
