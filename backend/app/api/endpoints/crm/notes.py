"""Native CRM — notes HTTP API (deal access roles; admin for mutations beyond create)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import crm_org_id, require_crm_deal_access, require_crm_deal_admin
from app.core.database import get_db
from app.models.users import User
from app.schemas.crm.activities_notes import (
    CrmNoteCreate,
    CrmNoteListResponse,
    CrmNoteRead,
    CrmNoteUpdate,
)
from app.services.crm.note_service import NoteServiceError, note_service

router = APIRouter(prefix="/crm/notes", tags=["crm-notes"])


def _http_error(exc: NoteServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmNoteListResponse, summary="List CRM notes")
async def list_notes(
    deal_id: uuid.UUID | None = Query(default=None),
    contact_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmNoteListResponse:
    return await note_service.list_notes(
        db,
        crm_org_id(current_user),
        deal_id=deal_id,
        contact_id=contact_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{note_id}", response_model=CrmNoteRead, summary="Get CRM note")
async def get_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmNoteRead:
    try:
        return await note_service.get_note(db, crm_org_id(current_user), note_id)
    except NoteServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmNoteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM note",
)
async def create_note(
    payload: CrmNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmNoteRead:
    try:
        return await note_service.create_note(
            db,
            crm_org_id(current_user),
            payload,
            author_id=current_user.id,
        )
    except NoteServiceError as exc:
        raise _http_error(exc) from exc


@router.patch("/{note_id}", response_model=CrmNoteRead, summary="Update CRM note")
async def update_note(
    note_id: uuid.UUID,
    payload: CrmNoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmNoteRead:
    try:
        return await note_service.update_note(
            db, crm_org_id(current_user), note_id, payload
        )
    except NoteServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM note",
)
async def delete_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> None:
    try:
        await note_service.delete_note(db, crm_org_id(current_user), note_id)
    except NoteServiceError as exc:
        raise _http_error(exc) from exc
