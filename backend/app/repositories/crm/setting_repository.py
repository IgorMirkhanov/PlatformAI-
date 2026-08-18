"""CRM settings repository — tenant-scoped get/upsert."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.setting import CrmSetting
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class SettingRepository(BaseCrmRepository[CrmSetting]):
    model = CrmSetting

    async def get_settings(self) -> CrmSetting | None:
        return await self.session.scalar(self._base_query())

    async def get_or_create(self, *, auto_capture_enabled: bool = True) -> CrmSetting:
        existing = await self.get_settings()
        if existing is not None:
            return existing
        entity = CrmSetting(
            organization_id=self.organization_id,
            auto_capture_enabled=auto_capture_enabled,
        )
        return await self.add(entity)


def setting_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> SettingRepository:
    return SettingRepository(session, organization_id=organization_id)
