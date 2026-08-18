"""CRM note service — CRUD with timeline note_added events."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.note import CrmNote
from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.deal_repository import deal_repository
from app.repositories.crm.note_repository import note_repository
from app.schemas.crm.activities_notes import (
    CrmNoteCreate,
    CrmNoteListResponse,
    CrmNoteRead,
    CrmNoteUpdate,
)
from app.services.crm.timeline_service import timeline_service


class NoteServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NoteService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return note_repository(db, organization_id=organization_id)

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
                raise NoteServiceError("Deal not found.", status_code=404)
        if contact_id is not None:
            if await contact_repository(db, organization_id=organization_id).get(contact_id) is None:
                raise NoteServiceError("Contact not found.", status_code=404)

    async def list_notes(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CrmNoteListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_filtered(
            deal_id=deal_id, contact_id=contact_id, limit=limit, offset=offset
        )
        total = await repo.count_filtered(deal_id=deal_id, contact_id=contact_id)
        return CrmNoteListResponse(
            items=[CrmNoteRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_note(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        note_id: uuid.UUID,
    ) -> CrmNoteRead:
        row = await self._repo(db, organization_id).get(note_id)
        if row is None:
            raise NoteServiceError("Note not found.", status_code=404)
        return CrmNoteRead.model_validate(row)

    async def create_note(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmNoteCreate,
        *,
        author_id: uuid.UUID | None = None,
    ) -> CrmNoteRead:
        await self._assert_targets(
            db,
            organization_id,
            deal_id=payload.deal_id,
            contact_id=payload.contact_id,
        )
        entity = CrmNote(
            organization_id=organization_id,
            deal_id=payload.deal_id,
            contact_id=payload.contact_id,
            author_id=author_id,
            text=payload.text,
        )
        await self._repo(db, organization_id).add(entity)
        await timeline_service.log_event(
            db,
            organization_id,
            event_type="note_added",
            deal_id=payload.deal_id,
            contact_id=payload.contact_id,
            actor_id=author_id,
            payload={"note_id": str(entity.id)},
        )
        return CrmNoteRead.model_validate(entity)

    async def update_note(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        note_id: uuid.UUID,
        payload: CrmNoteUpdate,
    ) -> CrmNoteRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(note_id)
        if entity is None:
            raise NoteServiceError("Note not found.", status_code=404)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entity, key, value)
        await db.flush()
        return CrmNoteRead.model_validate(entity)

    async def delete_note(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        note_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(note_id)
        if entity is None:
            raise NoteServiceError("Note not found.", status_code=404)
        await repo.delete(entity)


note_service = NoteService()
