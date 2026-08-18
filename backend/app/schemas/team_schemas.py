from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.core_models import TeamInvitationStatus, UserRole


class TeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    company_name: str
    company_id: uuid.UUID
    role: UserRole
    created_at: datetime


class TeamInvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    email: str
    role: UserRole
    expires_at: datetime
    status: TeamInvitationStatus
    created_at: datetime


class TeamMembersResponse(BaseModel):
    company_id: uuid.UUID
    members: list[TeamMemberRead]
    pending_invitations: list[TeamInvitationRead]
    total_members: int
    total_pending: int


class TeamInviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: UserRole = Field(default=UserRole.OPERATOR)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or "." not in normalized.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return normalized

    @field_validator("role")
    @classmethod
    def reject_owner_invite(cls, role: UserRole) -> UserRole:
        if role == UserRole.OWNER:
            raise ValueError("Cannot invite users with OWNER role.")
        return role


class TeamInviteResponse(BaseModel):
    invitation_id: uuid.UUID
    email: str
    role: UserRole
    token: str
    expires_at: datetime
    message: str = "Team invitation created."


class AcceptTeamInviteRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("Invalid email address.")
        return normalized


class AcceptTeamInviteResponse(BaseModel):
    user_id: uuid.UUID
    company_id: uuid.UUID
    email: str
    role: UserRole
    message: str = "Invitation accepted successfully."


class UpdateTeamMemberRoleRequest(BaseModel):
    role: UserRole

    @field_validator("role")
    @classmethod
    def validate_assignable_role(cls, role: UserRole) -> UserRole:
        # OWNER is allowed only for OWNER actors (enforced in service).
        return role


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    company_name: str
    company_id: uuid.UUID
    role: UserRole
    timezone: str = "Asia/Almaty"
    is_superadmin: bool = False
    is_support: bool = False
    created_at: datetime


class CompanyWorkspaceRead(BaseModel):
    id: uuid.UUID
    name: str
    role: UserRole
    timezone: str
    is_active: bool = False


class OrganizationsListResponse(BaseModel):
    active_company_id: uuid.UUID
    organizations: list[CompanyWorkspaceRead]


class CreateCompanyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class CreateCompanyResponse(BaseModel):
    company: CompanyWorkspaceRead
    access_token: str | None = None
    message: str = "Organization created successfully."


class SwitchCompanyRequest(BaseModel):
    company_id: uuid.UUID


class SwitchCompanyResponse(BaseModel):
    company_id: uuid.UUID
    company_name: str
    role: UserRole
    timezone: str
    access_token: str | None = None
    message: str = "Active workspace switched."


class UpdateCurrentUserRequest(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
