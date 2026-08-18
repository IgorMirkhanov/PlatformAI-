"""CRM settings service — get / update auto-capture toggle."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.crm.setting_repository import setting_repository
from app.schemas.crm.settings import CrmSettingRead, CrmSettingUpdate


class SettingServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SettingService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return setting_repository(db, organization_id=organization_id)

    async def get(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> CrmSettingRead:
        row = await self._repo(db, organization_id).get_or_create()
        return CrmSettingRead.model_validate(row)

    async def update(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmSettingUpdate,
    ) -> CrmSettingRead:
        repo = self._repo(db, organization_id)
        row = await repo.get_or_create()
        data = payload.model_dump(exclude_unset=True)
        if "auto_capture_enabled" in data:
            row.auto_capture_enabled = bool(data["auto_capture_enabled"])
        await db.flush()
        return CrmSettingRead.model_validate(row)


setting_service = SettingService()
