"""CRM deal repository."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.core_models import UserRole
from app.models.crm.deal import CrmDeal, DealStatus
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class DealRepository(BaseCrmRepository[CrmDeal]):
    model = CrmDeal

    def __init__(
        self,
        session: AsyncSession,
        *,
        organization_id: uuid.UUID,
        viewer_user_id: uuid.UUID | None = None,
        viewer_role: UserRole | None = None,
    ) -> None:
        super().__init__(session, organization_id=organization_id)
        self.viewer_user_id = viewer_user_id
        self.viewer_role = viewer_role

    @property
    def _viewer_scoped(self) -> bool:
        """True when OPERATOR (or other non-global role) scoping must apply."""
        # Lazy import avoids circular edges via app.repositories.crm ↔ app.services.crm.
        from app.services.crm.deal_access import CRM_GLOBAL_DEAL_ROLES

        if self.viewer_user_id is None:
            return False
        if self.viewer_role is None:
            return True
        return self.viewer_role not in CRM_GLOBAL_DEAL_ROLES

    def _apply_viewer_scope(self, stmt: Select) -> Select:
        if not self._viewer_scoped:
            return stmt
        return stmt.where(
            or_(
                CrmDeal.assigned_user_id == self.viewer_user_id,
                CrmDeal.assigned_user_id.is_(None),
            )
        )

    def _scoped_query(self) -> Select:
        return self._apply_viewer_scope(self._base_query())

    def _list_options(self):
        return (
            joinedload(CrmDeal.stage),
            joinedload(CrmDeal.contact),
            joinedload(CrmDeal.account),
            joinedload(CrmDeal.pipeline),
        )

    async def get(self, entity_id: uuid.UUID) -> CrmDeal | None:
        stmt = self._scoped_query().where(CrmDeal.id == entity_id)
        return await self.session.scalar(stmt)

    async def get_unscoped(self, entity_id: uuid.UUID) -> CrmDeal | None:
        """Tenant-only lookup (ignores operator per-deal scope)."""
        stmt = self._base_query().where(CrmDeal.id == entity_id)
        return await self.session.scalar(stmt)

    async def get_with_relations(self, deal_id: uuid.UUID) -> CrmDeal | None:
        stmt = (
            self._scoped_query()
            .where(CrmDeal.id == deal_id)
            .options(*self._list_options())
        )
        return await self.session.scalar(stmt)

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        """Tenant-only get with relations — used for mutation auth (404 vs 403)."""
        stmt = (
            self._base_query()
            .where(CrmDeal.id == deal_id)
            .options(*self._list_options())
        )
        return await self.session.scalar(stmt)

    async def get_deals(
        self,
        *,
        pipeline_id: uuid.UUID | None = None,
        stage_id: uuid.UUID | None = None,
        status: DealStatus | None = None,
        contact_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrmDeal]:
        stmt = (
            self._scoped_query()
            .options(*self._list_options())
            .order_by(CrmDeal.updated_at.desc())
        )
        if pipeline_id is not None:
            stmt = stmt.where(CrmDeal.pipeline_id == pipeline_id)
        if stage_id is not None:
            stmt = stmt.where(CrmDeal.stage_id == stage_id)
        if status is not None:
            stmt = stmt.where(CrmDeal.status == status)
        if contact_id is not None:
            stmt = stmt.where(CrmDeal.contact_id == contact_id)
        if account_id is not None:
            stmt = stmt.where(CrmDeal.account_id == account_id)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(CrmDeal.title.ilike(pattern))
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.unique().all())

    async def count_deals(
        self,
        *,
        pipeline_id: uuid.UUID | None = None,
        stage_id: uuid.UUID | None = None,
        status: DealStatus | None = None,
        contact_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None,
        q: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(CrmDeal).where(
            CrmDeal.organization_id == self.organization_id
        )
        if self._viewer_scoped:
            stmt = stmt.where(
                or_(
                    CrmDeal.assigned_user_id == self.viewer_user_id,
                    CrmDeal.assigned_user_id.is_(None),
                )
            )
        if pipeline_id is not None:
            stmt = stmt.where(CrmDeal.pipeline_id == pipeline_id)
        if stage_id is not None:
            stmt = stmt.where(CrmDeal.stage_id == stage_id)
        if status is not None:
            stmt = stmt.where(CrmDeal.status == status)
        if contact_id is not None:
            stmt = stmt.where(CrmDeal.contact_id == contact_id)
        if account_id is not None:
            stmt = stmt.where(CrmDeal.account_id == account_id)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(CrmDeal.title.ilike(pattern))
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def count_for_pipeline(self, pipeline_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(CrmDeal).where(
            CrmDeal.organization_id == self.organization_id,
            CrmDeal.pipeline_id == pipeline_id,
        )
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def get_latest_open_for_contact(self, contact_id: uuid.UUID) -> CrmDeal | None:
        # Internal bridge path — never apply operator viewer scope.
        stmt = (
            self._base_query()
            .where(
                CrmDeal.contact_id == contact_id,
                CrmDeal.status == DealStatus.OPEN,
            )
            .order_by(CrmDeal.updated_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)


def deal_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    viewer_user_id: uuid.UUID | None = None,
    viewer_role: UserRole | None = None,
) -> DealRepository:
    return DealRepository(
        session,
        organization_id=organization_id,
        viewer_user_id=viewer_user_id,
        viewer_role=viewer_role,
    )
