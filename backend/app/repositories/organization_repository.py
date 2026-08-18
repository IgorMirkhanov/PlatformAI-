"""Organization / Project repositories."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.core_models import (
    Company,
    Organization,
    Project,
    Subscription,
    SubscriptionStatus,
    UserCompanyWorkspace,
)
from app.repositories.base import TenantRepository


class OrganizationRepository:
    """Organization access (tenant root — filtered by membership, not org_id)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: uuid.UUID) -> Organization | None:
        stmt = (
            select(Company)
            .where(
                Company.id == org_id,
                Company.deleted_at.is_(None),
            )
            .options(selectinload(Company.memberships))
        )
        return await self.session.scalar(stmt)

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = (
            select(Company)
            .where(
                Company.slug == slug.strip().lower(),
                Company.deleted_at.is_(None),
            )
            .options(selectinload(Company.memberships))
        )
        return await self.session.scalar(stmt)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        """List orgs for a user with memberships eagerly loaded (no N+1)."""
        stmt = (
            select(Company)
            .join(
                UserCompanyWorkspace,
                UserCompanyWorkspace.company_id == Company.id,
            )
            .where(
                UserCompanyWorkspace.user_id == user_id,
                Company.deleted_at.is_(None),
            )
            .options(selectinload(Company.memberships))
            .order_by(Company.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        return list(result.unique().all())

    async def active_subscriptions_by_owner(
        self,
        owner_user_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Subscription]:
        """Batch-load the latest active Subscription per owner user id."""
        if not owner_user_ids:
            return {}
        result = await self.session.execute(
            select(Subscription)
            .where(
                Subscription.user_id.in_(owner_user_ids),
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.user_id, Subscription.updated_at.desc())
        )
        latest: dict[uuid.UUID, Subscription] = {}
        for sub in result.scalars().all():
            if sub.user_id not in latest:
                latest[sub.user_id] = sub
        return latest

    async def members_count_by_org(
        self,
        org_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        if not org_ids:
            return {}
        result = await self.session.execute(
            select(
                UserCompanyWorkspace.company_id,
                func.count(UserCompanyWorkspace.id),
            )
            .where(UserCompanyWorkspace.company_id.in_(org_ids))
            .group_by(UserCompanyWorkspace.company_id)
        )
        return {org_id: int(count or 0) for org_id, count in result.all()}


class ProjectRepository(TenantRepository[Project]):
    model = Project
    tenant_field = "organization_id"

    async def get_by_slug(self, slug: str) -> Project | None:
        stmt = self._base_query().where(Project.slug == slug)
        return await self.session.scalar(stmt)


def organization_repository(session: AsyncSession) -> OrganizationRepository:
    return OrganizationRepository(session)


def project_repository(
    session: AsyncSession,
    organization_id: uuid.UUID | None,
) -> ProjectRepository:
    return ProjectRepository(session, organization_id=organization_id)
