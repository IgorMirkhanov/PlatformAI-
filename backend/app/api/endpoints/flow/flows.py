"""Flow Builder CRUD + test-run API (organization-scoped)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_flows, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.org_flows import (
    OrgFlowCreate,
    OrgFlowListResponse,
    OrgFlowOut,
    OrgFlowTestRunRequest,
    OrgFlowTestRunResponse,
    OrgFlowUpdate,
)
from app.services.flow.flow_crud_service import (
    FlowServiceError,
    flow_crud_service,
    graph_from_flow,
)

router = APIRouter(prefix="/flows", tags=["flows"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_flow_manager(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_flows(role):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied: can_manage_flows required.",
    )


def _http_error(exc: FlowServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _to_out(flow) -> OrgFlowOut:
    nodes, edges = graph_from_flow(flow)
    return OrgFlowOut(
        id=flow.id,
        organization_id=flow.organization_id,
        name=flow.name,
        is_active=flow.is_active,
        nodes=nodes,
        edges=edges,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
    )


@router.get(
    "",
    response_model=OrgFlowListResponse,
    summary="List organization flows",
)
async def list_flows(
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrgFlowListResponse:
    _require_flow_manager(current_user)
    items = await flow_crud_service.list_flows(
        db,
        _org_id(current_user),
        active_only=active_only,
    )
    return OrgFlowListResponse(items=[_to_out(i) for i in items], total=len(items))


@router.post(
    "",
    response_model=OrgFlowOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create flow graph",
)
async def create_flow(
    payload: OrgFlowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrgFlowOut:
    _require_flow_manager(current_user)
    try:
        flow = await flow_crud_service.create_flow(
            db,
            _org_id(current_user),
            name=payload.name,
            nodes=payload.nodes,
            edges=payload.edges,
            is_active=payload.is_active,
        )
        await db.commit()
    except FlowServiceError as exc:
        raise _http_error(exc) from exc
    return _to_out(flow)


@router.get(
    "/{flow_id}",
    response_model=OrgFlowOut,
    summary="Get flow by id",
)
async def get_flow(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrgFlowOut:
    _require_flow_manager(current_user)
    try:
        flow = await flow_crud_service.get_flow(db, flow_id, _org_id(current_user))
    except FlowServiceError as exc:
        raise _http_error(exc) from exc
    return _to_out(flow)


@router.put(
    "/{flow_id}",
    response_model=OrgFlowOut,
    summary="Update flow graph",
)
async def update_flow(
    flow_id: uuid.UUID,
    payload: OrgFlowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrgFlowOut:
    _require_flow_manager(current_user)
    try:
        flow = await flow_crud_service.update_flow(
            db,
            flow_id,
            _org_id(current_user),
            name=payload.name,
            nodes=payload.nodes,
            edges=payload.edges,
            is_active=payload.is_active,
        )
        await db.commit()
    except FlowServiceError as exc:
        raise _http_error(exc) from exc
    return _to_out(flow)


@router.delete(
    "/{flow_id}",
    response_model=OrgFlowOut,
    summary="Deactivate (soft-delete) flow",
)
async def delete_flow(
    flow_id: uuid.UUID,
    hard: bool = Query(False, description="Permanently delete when true"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrgFlowOut:
    _require_flow_manager(current_user)
    try:
        flow = await flow_crud_service.delete_flow(
            db,
            flow_id,
            _org_id(current_user),
            hard=hard,
        )
        await db.commit()
    except FlowServiceError as exc:
        raise _http_error(exc) from exc
    return _to_out(flow)


@router.post(
    "/{flow_id}/test-run",
    response_model=OrgFlowTestRunResponse,
    summary="Test-run flow with a simulated inbound message",
)
async def test_run_flow(
    flow_id: uuid.UUID,
    payload: OrgFlowTestRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrgFlowTestRunResponse:
    _require_flow_manager(current_user)
    org_id = _org_id(current_user)
    try:
        flow = await flow_crud_service.get_flow(db, flow_id, org_id)
    except FlowServiceError as exc:
        raise _http_error(exc) from exc

    nodes, edges = graph_from_flow(flow)
    graph = {"nodes": nodes, "edges": edges}
    session_id = payload.session_id or f"test-{uuid.uuid4().hex[:12]}"
    initial_input = {
        "message": payload.message,
        "sender_id": payload.sender_id,
        "organization_id": str(org_id),
        **dict(payload.variables or {}),
    }

    from app.services.flow.engine import FlowEngineError, FlowExecutionLoopError
    from app.services.flow.executor import execute_flow

    try:
        result = await execute_flow(
            db,
            str(flow.id),
            session_id,
            initial_input,
            graph=graph,
            organization_id=org_id,
            raise_on_loop=False,
        )
    except (FlowEngineError, FlowExecutionLoopError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return OrgFlowTestRunResponse(
        session_id=result.session_id,
        flow_id=result.flow_id,
        status=result.status,
        steps_executed=result.steps_executed,
        path=list(result.path),
        variables=dict(result.variables),
        outputs=list(result.outputs),
        error=result.error,
        is_terminal=result.is_terminal,
    )
