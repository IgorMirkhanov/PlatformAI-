"""Native CRM — automation rules HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.crm.automation_rule import AutomationTriggerType
from app.models.users import User
from app.schemas.crm.automations import (
    CrmAutomationRuleCreate,
    CrmAutomationRuleListResponse,
    CrmAutomationRuleRead,
    CrmAutomationRuleUpdate,
)
from app.services.crm.automation_rule_service import (
    AutomationRuleServiceError,
    automation_rule_service,
)

router = APIRouter(prefix="/crm/automations", tags=["crm-automations"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: AutomationRuleServiceError) -> HTTPException:
    if exc.status_code == status.HTTP_402_PAYMENT_REQUIRED:
        return HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "crm_automation_rules_limit",
                "message": exc.message,
                "billing_url": "/billing",
            },
        )
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=CrmAutomationRuleListResponse,
    summary="List CRM automation rules",
)
async def list_automation_rules(
    is_active: bool | None = Query(default=None),
    trigger_type: AutomationTriggerType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAutomationRuleListResponse:
    return await automation_rule_service.list_rules(
        db,
        _org_id(current_user),
        is_active=is_active,
        trigger_type=trigger_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{rule_id}",
    response_model=CrmAutomationRuleRead,
    summary="Get CRM automation rule",
)
async def get_automation_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAutomationRuleRead:
    try:
        return await automation_rule_service.get_rule(db, _org_id(current_user), rule_id)
    except AutomationRuleServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmAutomationRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM automation rule",
)
async def create_automation_rule(
    payload: CrmAutomationRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAutomationRuleRead:
    try:
        return await automation_rule_service.create_rule(db, _org_id(current_user), payload)
    except AutomationRuleServiceError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{rule_id}",
    response_model=CrmAutomationRuleRead,
    summary="Update CRM automation rule",
)
async def update_automation_rule(
    rule_id: uuid.UUID,
    payload: CrmAutomationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAutomationRuleRead:
    try:
        return await automation_rule_service.update_rule(
            db, _org_id(current_user), rule_id, payload
        )
    except AutomationRuleServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM automation rule",
)
async def delete_automation_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await automation_rule_service.delete_rule(db, _org_id(current_user), rule_id)
    except AutomationRuleServiceError as exc:
        raise _http_error(exc) from exc
