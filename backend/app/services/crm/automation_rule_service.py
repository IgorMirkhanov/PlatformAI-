"""CRM automation rule service — CRUD only (no evaluator in Phase B step 1)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.repositories.crm.automation_rule_repository import automation_rule_repository
from app.schemas.crm.automations import (
    CrmAutomationRuleCreate,
    CrmAutomationRuleListResponse,
    CrmAutomationRuleRead,
    CrmAutomationRuleUpdate,
)


class AutomationRuleServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AutomationRuleService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return automation_rule_repository(db, organization_id=organization_id)

    async def list_rules(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        is_active: bool | None = None,
        trigger_type: AutomationTriggerType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CrmAutomationRuleListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_filtered(
            is_active=is_active,
            trigger_type=trigger_type,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_filtered(is_active=is_active, trigger_type=trigger_type)
        return CrmAutomationRuleListResponse(
            items=[CrmAutomationRuleRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_rule(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        rule_id: uuid.UUID,
    ) -> CrmAutomationRuleRead:
        row = await self._repo(db, organization_id).get(rule_id)
        if row is None:
            raise AutomationRuleServiceError("Automation rule not found.", status_code=404)
        return CrmAutomationRuleRead.model_validate(row)

    async def create_rule(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmAutomationRuleCreate,
    ) -> CrmAutomationRuleRead:
        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            await quota_service.assert_crm_automation_rules_quota(db, organization_id)
        except QuotaExceeded as exc:
            raise AutomationRuleServiceError(exc.detail, status_code=402) from exc

        entity = CrmAutomationRule(
            organization_id=organization_id,
            name=payload.name,
            is_active=payload.is_active,
            trigger_type=payload.trigger_type,
            trigger_config=dict(payload.trigger_config or {}),
            conditions=dict(payload.conditions or {}),
            actions=list(payload.actions or []),
        )
        await self._repo(db, organization_id).add(entity)
        return CrmAutomationRuleRead.model_validate(entity)

    async def update_rule(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        rule_id: uuid.UUID,
        payload: CrmAutomationRuleUpdate,
    ) -> CrmAutomationRuleRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(rule_id)
        if entity is None:
            raise AutomationRuleServiceError("Automation rule not found.", status_code=404)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entity, key, value)
        await db.flush()
        return CrmAutomationRuleRead.model_validate(entity)

    async def delete_rule(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        rule_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(rule_id)
        if entity is None:
            raise AutomationRuleServiceError("Automation rule not found.", status_code=404)
        await repo.delete(entity)

    async def get_active_rules_by_trigger(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        trigger_type: AutomationTriggerType,
    ) -> list[CrmAutomationRuleRead]:
        rows = await self._repo(db, organization_id).get_active_rules_by_trigger(trigger_type)
        return [CrmAutomationRuleRead.model_validate(row) for row in rows]


automation_rule_service = AutomationRuleService()
