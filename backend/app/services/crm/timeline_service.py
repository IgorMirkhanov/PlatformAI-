"""CRM timeline service — append-only log_event + get_events."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.timeline_event import CrmTimelineEvent
from app.repositories.crm.timeline_repository import timeline_repository
from app.schemas.crm.activities_notes import CrmTimelineEventRead, CrmTimelineListResponse


class TimelineServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TimelineService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return timeline_repository(db, organization_id=organization_id)

    async def log_event(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        event_type: str,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CrmTimelineEvent:
        if not event_type.strip():
            raise TimelineServiceError("event_type is required.")
        if deal_id is None and contact_id is None:
            raise TimelineServiceError("Either deal_id or contact_id is required for timeline events.")

        event = CrmTimelineEvent(
            organization_id=organization_id,
            deal_id=deal_id,
            contact_id=contact_id,
            actor_id=actor_id,
            event_type=event_type.strip(),
            payload=dict(payload or {}),
        )
        await self._repo(db, organization_id).add(event)
        return event

    async def get_events(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CrmTimelineListResponse:
        if deal_id is None and contact_id is None:
            raise TimelineServiceError(
                "Filter by deal_id or contact_id is required.",
                status_code=400,
            )
        repo = self._repo(db, organization_id)
        items = await repo.list_events(
            deal_id=deal_id,
            contact_id=contact_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_events(
            deal_id=deal_id,
            contact_id=contact_id,
            event_type=event_type,
        )
        return CrmTimelineListResponse(
            items=[CrmTimelineEventRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )


timeline_service = TimelineService()
