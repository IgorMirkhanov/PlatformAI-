"""BYOK credentials vault API with optional provider ping before save."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_settings, get_current_user
from app.models.core_models import UserRole
from app.models.tenant_credentials import CredentialKind, CredentialStatus
from app.models.users import User
from app.repositories.credentials_repository import CredentialsRepository
from app.services.credential_validation import CredentialValidationError, validate_credential_payload

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialCreateRequest(BaseModel):
    kind: str = Field(min_length=3, max_length=64)
    payload: dict[str, Any]
    label: str | None = Field(default=None, max_length=255)
    validate_before_save: bool = True


class CredentialRead(BaseModel):
    id: uuid.UUID
    kind: str
    label: str | None = None
    status: str
    last_error: str | None = None
    last_validated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CredentialListResponse(BaseModel):
    items: list[CredentialRead]


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_settings(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_settings(role):
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")


def _to_read(row) -> CredentialRead:
    return CredentialRead(
        id=row.id,
        kind=row.kind,
        label=row.label,
        status=row.status,
        last_error=row.last_error,
        last_validated_at=row.last_validated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=CredentialListResponse)
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CredentialListResponse:
    _require_settings(current_user)
    rows = await CredentialsRepository(db).list_for_org(_org_id(current_user))
    return CredentialListResponse(items=[_to_read(row) for row in rows])


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(
    payload: CredentialCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CredentialRead:
    _require_settings(current_user)
    kind = payload.kind.strip().lower()
    allowed = {item.value for item in CredentialKind}
    if kind not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported credential kind. Allowed: {sorted(allowed)}",
        )
    if payload.validate_before_save:
        try:
            await validate_credential_payload(kind, payload.payload)
        except CredentialValidationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    row = await CredentialsRepository(db).upsert(
        organization_id=_org_id(current_user),
        kind=kind,
        payload=payload.payload,
        label=payload.label,
        status=CredentialStatus.ACTIVE.value,
    )
    row.last_validated_at = datetime.now(timezone.utc)
    row.last_error = None
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.post("/{credential_id}/validate", response_model=CredentialRead)
async def revalidate_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CredentialRead:
    _require_settings(current_user)
    repo = CredentialsRepository(db)
    row = await repo.get(credential_id)
    if row is None or row.organization_id != _org_id(current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")
    decrypted = await repo.get_decrypted(
        organization_id=row.organization_id,
        kind=row.kind,
        label=row.label,
    )
    try:
        await validate_credential_payload(row.kind, decrypted or {})
        row.status = CredentialStatus.ACTIVE.value
        row.last_error = None
        row.last_validated_at = datetime.now(timezone.utc)
    except CredentialValidationError as exc:
        row.status = CredentialStatus.ERROR.value
        row.last_error = exc.message[:2000]
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    await db.commit()
    await db.refresh(row)
    return _to_read(row)
