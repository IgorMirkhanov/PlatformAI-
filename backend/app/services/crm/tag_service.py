"""CRM tag service — CRUD + attach/detach on deals with timeline events."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.tag import CrmTag
from app.repositories.crm.deal_repository import deal_repository
from app.repositories.crm.tag_repository import tag_repository
from app.schemas.crm.tags_fields import (
    CrmTagCreate,
    CrmTagListResponse,
    CrmTagRead,
    CrmTagUpdate,
)
from app.services.crm.timeline_service import timeline_service


class TagServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TagService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return tag_repository(db, organization_id=organization_id)

    async def list_tags(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> CrmTagListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_ordered(limit=limit, offset=offset)
        total = await repo.count_all()
        return CrmTagListResponse(
            items=[CrmTagRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_tag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> CrmTagRead:
        row = await self._repo(db, organization_id).get(tag_id)
        if row is None:
            raise TagServiceError("Tag not found.", status_code=404)
        return CrmTagRead.model_validate(row)

    async def create_tag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmTagCreate,
    ) -> CrmTagRead:
        entity = CrmTag(
            organization_id=organization_id,
            name=payload.name,
            color=payload.color,
        )
        await self._repo(db, organization_id).add(entity)
        return CrmTagRead.model_validate(entity)

    async def update_tag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        tag_id: uuid.UUID,
        payload: CrmTagUpdate,
    ) -> CrmTagRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(tag_id)
        if entity is None:
            raise TagServiceError("Tag not found.", status_code=404)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entity, key, value)
        await db.flush()
        return CrmTagRead.model_validate(entity)

    async def delete_tag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(tag_id)
        if entity is None:
            raise TagServiceError("Tag not found.", status_code=404)
        await repo.delete(entity)

    async def attach_tag_to_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        tag_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> CrmTagRead:
        deals = deal_repository(db, organization_id=organization_id)
        tags = self._repo(db, organization_id)
        deal = await deals.get(deal_id)
        if deal is None:
            raise TagServiceError("Deal not found.", status_code=404)
        tag = await tags.get(tag_id)
        if tag is None:
            raise TagServiceError("Tag not found.", status_code=404)

        created = await tags.attach_to_deal(deal_id=deal_id, tag_id=tag_id)
        if created:
            await timeline_service.log_event(
                db,
                organization_id,
                event_type="tag_added",
                deal_id=deal_id,
                actor_id=actor_id,
                payload={"tag_id": str(tag_id), "tag_name": tag.name},
            )
        return CrmTagRead.model_validate(tag)

    async def remove_tag_from_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        tag_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        deals = deal_repository(db, organization_id=organization_id)
        tags = self._repo(db, organization_id)
        deal = await deals.get(deal_id)
        if deal is None:
            raise TagServiceError("Deal not found.", status_code=404)
        tag = await tags.get(tag_id)
        if tag is None:
            raise TagServiceError("Tag not found.", status_code=404)

        removed = await tags.detach_from_deal(deal_id=deal_id, tag_id=tag_id)
        if not removed:
            raise TagServiceError("Tag is not attached to this deal.", status_code=404)
        await timeline_service.log_event(
            db,
            organization_id,
            event_type="tag_removed",
            deal_id=deal_id,
            actor_id=actor_id,
            payload={"tag_id": str(tag_id), "tag_name": tag.name},
        )


tag_service = TagService()
