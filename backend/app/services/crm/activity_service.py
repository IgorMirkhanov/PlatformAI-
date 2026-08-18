"""CRM activity service — CRUD + complete."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.activity import ActivityType, CrmActivity
from app.repositories.crm.activity_repository import activity_repository
from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.deal_repository import deal_repository
from app.schemas.crm.activities_notes import (
    CrmActivityCreate,
    CrmActivityListResponse,
    CrmActivityRead,
    CrmActivityUpdate,
)


class ActivityServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ActivityService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return activity_repository(db, organization_id=organization_id)

    async def _assert_targets(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        deal_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
    ) -> None:
        if deal_id is not None:
            if await deal_repository(db, organization_id=organization_id).get(deal_id) is None:
                raise ActivityServiceError("Deal not found.", status_code=404)
        if contact_id is not None:
            if await contact_repository(db, organization_id=organization_id).get(contact_id) is None:
                raise ActivityServiceError("Contact not found.", status_code=404)

    async def list_activities(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        activity_type: ActivityType | None = None,
        only_open: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> CrmActivityListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_filtered(
            deal_id=deal_id,
            contact_id=contact_id,
            activity_type=activity_type,
            only_open=only_open,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_filtered(
            deal_id=deal_id,
            contact_id=contact_id,
            activity_type=activity_type,
            only_open=only_open,
        )
        return CrmActivityListResponse(
            items=[CrmActivityRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_activity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        activity_id: uuid.UUID,
    ) -> CrmActivityRead:
        row = await self._repo(db, organization_id).get(activity_id)
        if row is None:
            raise ActivityServiceError("Activity not found.", status_code=404)
        return CrmActivityRead.model_validate(row)

    async def create_activity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmActivityCreate,
        *,
        created_by_id: uuid.UUID | None = None,
    ) -> CrmActivityRead:
        await self._assert_targets(
            db,
            organization_id,
            deal_id=payload.deal_id,
            contact_id=payload.contact_id,
        )
        entity = CrmActivity(
            organization_id=organization_id,
            deal_id=payload.deal_id,
            contact_id=payload.contact_id,
            type=payload.type,
            title=payload.title,
            description=payload.description,
            due_at=payload.due_at,
            assigned_user_id=payload.assigned_user_id,
            created_by_id=created_by_id,
        )
        await self._repo(db, organization_id).add(entity)
        return CrmActivityRead.model_validate(entity)

    async def update_activity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        activity_id: uuid.UUID,
        payload: CrmActivityUpdate,
    ) -> CrmActivityRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(activity_id)
        if entity is None:
            raise ActivityServiceError("Activity not found.", status_code=404)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entity, key, value)
        await db.flush()
        return CrmActivityRead.model_validate(entity)

    async def delete_activity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        activity_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(activity_id)
        if entity is None:
            raise ActivityServiceError("Activity not found.", status_code=404)
        await repo.delete(entity)

    async def complete_activity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        activity_id: uuid.UUID,
    ) -> CrmActivityRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(activity_id)
        if entity is None:
            raise ActivityServiceError("Activity not found.", status_code=404)
        entity.completed_at = datetime.now(timezone.utc)
        await db.flush()
        try:
            from app.models.saas_metering import UsageMetricType
            from app.services.crm.crm_usage_events import record_crm_usage_event

            await record_crm_usage_event(
                db,
                organization_id=organization_id,
                metric_type=UsageMetricType.TASK_COMPLETED,
                user_id=entity.assigned_user_id or entity.created_by_id,
                meta={
                    "activity_id": str(entity.id),
                    "type": entity.type.value if hasattr(entity.type, "value") else str(entity.type),
                    "deal_id": str(entity.deal_id) if entity.deal_id else None,
                },
            )
        except Exception as exc:
            logger.warning(
                "CRM.usage_event_skipped | action=complete activity_id={activity_id} error={error}",
                activity_id=entity.id,
                error=str(exc),
            )
        return CrmActivityRead.model_validate(entity)


activity_service = ActivityService()
