"""CRM automation rule repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class AutomationRuleRepository(BaseCrmRepository[CrmAutomationRule]):
    model = CrmAutomationRule

    async def list_filtered(
        self,
        *,
        is_active: bool | None = None,
        trigger_type: AutomationTriggerType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CrmAutomationRule]:
        stmt = self._base_query().order_by(
            CrmAutomationRule.created_at.desc(),
            CrmAutomationRule.name.asc(),
        )
        if is_active is not None:
            stmt = stmt.where(CrmAutomationRule.is_active.is_(is_active))
        if trigger_type is not None:
            stmt = stmt.where(CrmAutomationRule.trigger_type == trigger_type)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_filtered(
        self,
        *,
        is_active: bool | None = None,
        trigger_type: AutomationTriggerType | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(CrmAutomationRule).where(
            CrmAutomationRule.organization_id == self.organization_id
        )
        if is_active is not None:
            stmt = stmt.where(CrmAutomationRule.is_active.is_(is_active))
        if trigger_type is not None:
            stmt = stmt.where(CrmAutomationRule.trigger_type == trigger_type)
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def get_active_rules_by_trigger(
        self,
        trigger_type: AutomationTriggerType,
    ) -> list[CrmAutomationRule]:
        stmt = (
            self._base_query()
            .where(
                CrmAutomationRule.is_active.is_(True),
                CrmAutomationRule.trigger_type == trigger_type,
            )
            .order_by(CrmAutomationRule.created_at.asc())
        )
        result = await self.session.scalars(stmt)
        return list(result.all())


def automation_rule_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> AutomationRuleRepository:
    return AutomationRuleRepository(session, organization_id=organization_id)
