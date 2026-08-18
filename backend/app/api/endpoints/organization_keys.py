"""Organization LLM API key management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_settings, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.organization_api_keys import (
    OrganizationApiKeyListResponse,
    OrganizationApiKeyUpsertRequest,
    OrganizationApiKeyUpsertResponse,
)
from app.services.ai_keys_service import AiKeysServiceError, ai_keys_service

router = APIRouter(prefix="/organizations/api-keys", tags=["organization-api-keys"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_settings_manager(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_settings(role):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied: manage settings required.",
    )


def _http_error(exc: AiKeysServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=OrganizationApiKeyListResponse,
    summary="List configured LLM API key providers (masked)",
)
async def list_organization_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationApiKeyListResponse:
    _require_settings_manager(current_user)
    return await ai_keys_service.list_provider_status(db, _org_id(current_user))


@router.post(
    "",
    response_model=OrganizationApiKeyUpsertResponse,
    summary="Create or update an organization LLM API key",
)
async def upsert_organization_api_key(
    payload: OrganizationApiKeyUpsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationApiKeyUpsertResponse:
    _require_settings_manager(current_user)
    try:
        response = await ai_keys_service.upsert_key(
            db,
            organization_id=_org_id(current_user),
            provider=payload.provider,
            api_key=payload.api_key,
            is_active=payload.is_active,
        )
        await db.commit()
        return response
    except AiKeysServiceError as exc:
        raise _http_error(exc) from exc
    except Exception as exc:
        logger.exception("OrganizationApiKeys.upsert_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save API key.",
        ) from exc


@router.delete(
    "/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete organization LLM API key for a provider",
)
async def delete_organization_api_key(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _require_settings_manager(current_user)
    try:
        await ai_keys_service.delete_key(
            db,
            organization_id=_org_id(current_user),
            provider=provider,
        )
        await db.commit()
    except AiKeysServiceError as exc:
        raise _http_error(exc) from exc
    except Exception as exc:
        logger.exception("OrganizationApiKeys.delete_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete API key.",
        ) from exc
