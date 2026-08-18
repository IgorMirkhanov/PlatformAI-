"""Organization workspace endpoints — list, usage quotas, tenancy helpers."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.core.rbac import Permission, ROLE_PERMISSIONS, get_current_user
from app.models.core_models import (
    Bot,
    Company,
    SubscriptionPlanName,
    SubscriptionStatus,
    UserCompanyWorkspace,
)
from app.models.users import User
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.team_schemas import TeamMembersResponse
from app.services.billing_service import PLAN_AGENT_LIMITS, billing_service
from app.services.team_service import TEAM_SEAT_LIMITS, team_service

router = APIRouter(prefix="/organizations", tags=["organizations"])

PLAN_TEAM_SEAT_LIMITS = TEAM_SEAT_LIMITS


@router.get(
    "/members",
    response_model=TeamMembersResponse,
    summary="List organization members (alias of /team/members)",
)
async def list_organization_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamMembersResponse:
    perms = ROLE_PERMISSIONS.get(current_user.role, frozenset())
    include_pending = Permission.TEAM_MANAGE in perms
    return await team_service.list_members(
        db,
        current_user=current_user,
        include_pending_invites=include_pending,
    )


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str | None
    timezone: str
    created_at: datetime
    members_count: int = 0
    subscription_plan: SubscriptionPlanName | None = None
    subscription_status: SubscriptionStatus | None = None
    wallet_balance: float | None = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationUsageResponse(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    plan_name: SubscriptionPlanName
    active_bots: int = Field(ge=0)
    active_bots_limit: int = Field(ge=0)
    team_slots_used: int = Field(ge=0)
    team_slots_limit: int = Field(ge=0)
    wallet_balance_kzt: float = 0.0
    is_low_balance: bool = False
    low_balance_threshold_kzt: float = 2500.0


@router.get("", response_model=list[OrganizationRead])
async def list_my_organizations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationRead]:
    """List workspaces with memberships + subscription eagerly batched."""
    repo = OrganizationRepository(db)
    orgs = await repo.list_for_user(current_user.id)
    if not orgs:
        return []

    org_ids = [org.id for org in orgs]
    owner_ids = list({org.owner_user_id for org in orgs})
    members_by_org = await repo.members_count_by_org(org_ids)
    subs_by_owner = await repo.active_subscriptions_by_owner(owner_ids)

    payload: list[OrganizationRead] = []
    for org in orgs:
        # Prefer already-eager memberships length; fall back to batch count.
        members_count = (
            len(org.memberships)
            if getattr(org, "memberships", None) is not None
            else members_by_org.get(org.id, 0)
        )
        if members_count == 0:
            members_count = members_by_org.get(org.id, 0)

        sub = subs_by_owner.get(org.owner_user_id)
        payload.append(
            OrganizationRead(
                id=org.id,
                name=org.name,
                slug=org.slug,
                timezone=org.timezone,
                created_at=org.created_at,
                members_count=members_count,
                subscription_plan=sub.plan_name if sub else None,
                subscription_status=sub.status if sub else None,
                wallet_balance=float(sub.balance) if sub else None,
            )
        )
    return payload


@router.get("/usage", response_model=OrganizationUsageResponse)
async def get_organization_usage(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> OrganizationUsageResponse:
    """Quota snapshot for the active workspace (bots + team seats)."""
    company_id = current_user.company_id
    company = await db.get(Company, company_id)
    company_name = company.name if company is not None else current_user.company_name

    # Org billing is owned by the workspace owner, not the acting member.
    billing_user_id = company.owner_user_id if company is not None else current_user.id
    billing = await billing_service.get_billing_status(db, billing_user_id)
    plan = billing.plan_name

    bots_count = await db.scalar(
        select(func.count())
        .select_from(Bot)
        .where(
            Bot.organization_id == company_id,
            Bot.deleted_at.is_(None),
        )
    )
    seats_used = await db.scalar(
        select(func.count())
        .select_from(UserCompanyWorkspace)
        .where(UserCompanyWorkspace.company_id == company_id)
    )

    return OrganizationUsageResponse(
        organization_id=company_id,
        organization_name=company_name or "Workspace",
        plan_name=plan,
        active_bots=int(bots_count or 0),
        active_bots_limit=int(billing.active_agents_limit or PLAN_AGENT_LIMITS[plan]),
        team_slots_used=int(seats_used or 0),
        team_slots_limit=PLAN_TEAM_SEAT_LIMITS.get(plan, 3),
        wallet_balance_kzt=float(billing.balance),
        is_low_balance=bool(billing.is_low_balance),
        low_balance_threshold_kzt=float(billing.low_balance_threshold_kzt),
    )
