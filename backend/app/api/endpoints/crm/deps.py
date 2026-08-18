"""CRM FastAPI dependencies — org context, role gates, API-key auth."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.users import User
from app.services.crm.api_key_service import VerifiedCrmApiKey, api_key_service
from app.services.crm.deal_access import (
    CRM_DEAL_ACCESS_ROLES,
    CRM_DEAL_ADMIN_ROLES,
    CrmActor,
)


def crm_org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def crm_actor(user: User) -> CrmActor:
    return CrmActor.from_user(user)


require_crm_deal_access = require_roles(*CRM_DEAL_ACCESS_ROLES)
require_crm_deal_admin = require_roles(*CRM_DEAL_ADMIN_ROLES)

CrmDealUser = Annotated[User, Depends(require_crm_deal_access)]
CrmDealAdminUser = Annotated[User, Depends(require_crm_deal_admin)]


def _extract_crm_api_key(
    *,
    authorization: str | None,
    x_crm_api_key: str | None,
) -> str | None:
    if x_crm_api_key and x_crm_api_key.strip():
        return x_crm_api_key.strip()
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
        if len(parts) == 1 and parts[0].startswith("mpai_crm_"):
            return parts[0].strip()
    return None


async def verify_crm_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_crm_api_key: str | None = Header(default=None, alias="X-CRM-API-Key"),
) -> VerifiedCrmApiKey:
    """
    Authenticate public CRM inbound calls via API key (no JWT).

    Accepts ``Authorization: Bearer <key>`` or ``X-CRM-API-Key: <key>``.
    """
    raw = _extract_crm_api_key(authorization=authorization, x_crm_api_key=x_crm_api_key)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CRM API key required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    verified = await api_key_service.verify_raw_key(db, raw)
    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive CRM API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.crm_organization_id = verified.organization_id
    return verified


VerifiedCrmApiKeyDep = Annotated[VerifiedCrmApiKey, Depends(verify_crm_api_key)]
