"""Integration Hub REST API — tenant connections (secrets never returned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission, assert_permission, get_current_user
from app.models.core_models import Bot, UserRole
from app.models.integration_hub import IntegrationConnection, IntegrationUsageEvent
from app.models.users import User
from app.services.integration_hub.oauth import (
    OAuthFlowError,
    callback_url,
    disconnect_connection,
    frontend_result_url,
    handle_callback,
    start_authorize,
)
from app.services.integration_hub.service import integration_hub_service
from app.services.integration_hub.tenancy import get_connection_for_workspace

router = APIRouter(prefix="/integrations/hub", tags=["integration-hub"])
oauth_router = APIRouter(prefix="/integrations", tags=["integration-hub-oauth"])

OAuthProvider = Literal["amocrm", "bitrix24", "kommo"]


class HubConnectRequest(BaseModel):
    provider: str = Field(min_length=3, max_length=32)
    bot_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class HubTestConnectionRequest(BaseModel):
    provider: str = Field(min_length=3, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class HubConnectionRead(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    bot_id: uuid.UUID | None
    external_account_id: str | None
    config: dict[str, Any]
    metadata: dict[str, Any]
    oauth_expires_at: datetime | None
    last_error: str | None
    updated_at: datetime


def _to_read(row: IntegrationConnection) -> HubConnectionRead:
    config = dict(row.config_json or {})
    meta = config.get("metadata")
    if not isinstance(meta, dict):
        meta = {"channels": config.get("channels") or []}
    return HubConnectionRead(
        id=row.id,
        provider=row.provider,
        status=row.status,
        bot_id=row.bot_id,
        external_account_id=row.external_account_id,
        config=config,
        metadata=meta,
        oauth_expires_at=row.oauth_expires_at,
        last_error=row.last_error,
        updated_at=row.updated_at,
    )


def _workspace_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None) or getattr(user, "organization_id", None)
    if org_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Workspace is not selected.")
    assert_permission(user.role or UserRole.OPERATOR, Permission.BOT_INTEGRATIONS)
    return org_id


@router.get("/connections", summary="List Integration Hub connections for the workspace")
async def list_hub_connections(
    bot_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _workspace_id(user)
    rows = await integration_hub_service.list_connections(
        db, organization_id=org_id, bot_id=bot_id
    )
    return {"connections": [_to_read(row).model_dump() for row in rows]}


@router.post(
    "/connections",
    summary="Connect a provider using the platform OAuth app + tenant payload",
)
async def create_hub_connection(
    body: HubConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _workspace_id(user)
    if body.bot_id is not None:
        bot = await db.scalar(select(Bot).where(Bot.id == body.bot_id))
        if bot is None or bot.organization_id != org_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    try:
        row = await integration_hub_service.connect(
            db,
            organization_id=org_id,
            bot_id=body.bot_id,
            provider=body.provider,
            payload=body.payload,
        )
        await db.commit()
        await db.refresh(row)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"connection": _to_read(row).model_dump(), "message": f"{body.provider} подключён."}


@router.post(
    "/connections/test",
    summary="Validate API-key credentials via testConnection() without saving",
)
async def test_hub_connection(
    body: HubTestConnectionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _ = _workspace_id(user)
    from app.services.integration_hub.adapters import get_hub_adapter
    from app.services.integration_hub.oauth_apps import get_platform_oauth_app
    from app.services.integration_hub.types import TokenBundle

    key = (body.provider or "").strip().lower()
    if key in {"amocrm", "kommo"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="OAuth-провайдер подключается через кнопку «Подключить», не через API-ключ.",
        )
    if key == "bitrix24" and not str((body.payload or {}).get("webhook_url") or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Для Bitrix24 укажите Incoming Webhook URL или настройте BITRIX_APP_ID для OAuth.",
        )
    try:
        adapter = get_hub_adapter(key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    tester = getattr(adapter, "test_connection", None)
    if not callable(tester):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Провайдер не поддерживает testConnection.",
        )
    platform_app = await get_platform_oauth_app(db, key)
    import httpx

    dummy_id = uuid.uuid4()
    async with httpx.AsyncClient(timeout=20.0) as http:
        try:
            bundle = await adapter.connect(
                platform_app=platform_app,
                payload=body.payload,
                http=http,
            )
            ok = await tester(secrets=bundle, http=http, connection_id=dummy_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Не удалось проверить подключение. Проверьте ключ.",
            ) from exc
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Ключ отклонён провайдером.")
    extra = bundle.extra if isinstance(bundle, TokenBundle) else {}
    metadata: dict[str, Any] = {}
    if isinstance(extra, dict):
        if extra.get("metadata"):
            metadata = dict(extra["metadata"])
        elif extra.get("channels"):
            metadata = {"channels": extra["channels"]}
        if extra.get("merchant_id"):
            metadata["merchant_id"] = extra["merchant_id"]
    return {
        "ok": True,
        "provider": key,
        "external_account_id": getattr(bundle, "external_account_id", None),
        "metadata": metadata,
    }


@router.post(
    "/bots/{bot_id}/connections",
    summary="Connect a provider for a specific agent",
)
async def create_hub_connection_for_bot(
    bot_id: uuid.UUID,
    body: HubConnectRequest,
    db: AsyncSession = Depends(get_db),
    bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    org_id = bot.organization_id
    if org_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Agent has no organization.")
    try:
        row = await integration_hub_service.connect(
            db,
            organization_id=org_id,
            bot_id=bot_id,
            provider=body.provider,
            payload=body.payload,
        )
        await db.commit()
        await db.refresh(row)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"connection": _to_read(row).model_dump(), "message": f"{body.provider} подключён."}


@router.delete("/connections/{connection_id}")
async def delete_hub_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    org_id = _workspace_id(user)
    row = await get_connection_for_workspace(
        db, connection_id=connection_id, organization_id=org_id
    )
    await disconnect_connection(db, row)
    await db.commit()
    return {"message": "Интеграция отключена."}


@router.get(
    "/oauth-redirect-uris",
    summary="Canonical OAuth redirect URIs for partner cabinets",
)
async def oauth_redirect_uris(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Exact redirect_uri strings for Bitrix24 / amoCRM partner cabinets."""
    _ = _workspace_id(user)
    return {
        "bitrix24": callback_url("bitrix24"),
        "amocrm": callback_url("amocrm"),
        "kommo": callback_url("amocrm"),
        "note": (
            "Register these URLs character-for-character (https, no trailing slash). "
            "Derived from WEBHOOK_BASE_URL / NGROK_TUNNEL_URL."
        ),
    }


@router.get(
    "/usage-events",
    summary="List Integration Hub usage events for the caller's workspace",
)
async def list_hub_usage_events(
    workspace_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Tenant-scoped metering rows. Foreign workspace_id → 403."""
    org_id = _workspace_id(user)
    if workspace_id is not None and workspace_id != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Workspace mismatch.")
    rows = list(
        (
            await db.scalars(
                select(IntegrationUsageEvent)
                .where(IntegrationUsageEvent.organization_id == org_id)
                .order_by(IntegrationUsageEvent.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return {
        "workspace_id": str(org_id),
        "events": [
            {
                "id": str(row.id),
                "connection_id": str(row.connection_id) if row.connection_id else None,
                "metric": row.metric,
                "quantity": row.quantity,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get(
    "/connections/{connection_id}",
    summary="Get one Integration Hub connection (workspace-scoped, no secrets)",
)
async def get_hub_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _workspace_id(user)
    row = await get_connection_for_workspace(
        db, connection_id=connection_id, organization_id=org_id
    )
    return {"connection": _to_read(row).model_dump()}


@oauth_router.get(
    "/connections/{connection_id}",
    summary="Get one connection by id (alias; cross-tenant → 404)",
)
async def get_integration_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Public path used by QA checklist: /api/v1/integrations/connections/{id}."""
    org_id = _workspace_id(user)
    row = await get_connection_for_workspace(
        db, connection_id=connection_id, organization_id=org_id
    )
    payload = _to_read(row).model_dump()
    payload["workspace_id"] = row.organization_id
    payload["agent_id"] = row.bot_id
    return {"connection": payload}


@oauth_router.get("", summary="List workspace connections (no secrets)")
async def list_integrations(
    workspace_id: uuid.UUID | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    org_id = _workspace_id(user)
    if workspace_id is not None and workspace_id != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Workspace mismatch.")
    rows = await integration_hub_service.list_connections(
        db, organization_id=org_id, bot_id=agent_id
    )
    return {
        "connections": [
            {
                **_to_read(row).model_dump(),
                "workspace_id": row.organization_id,
                "agent_id": row.bot_id,
            }
            for row in rows
        ]
    }


@oauth_router.get(
    "/{provider}/authorize",
    summary="Start platform OAuth2 (Bitrix24 / amoCRM)",
    response_model=None,
)
async def oauth_authorize(
    provider: OAuthProvider,
    workspace_id: uuid.UUID = Query(...),
    agent_id: uuid.UUID | None = Query(default=None),
    subdomain: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    response_format: str | None = Query(default=None, alias="format"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RedirectResponse | JSONResponse:
    org_id = _workspace_id(user)
    if workspace_id != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Workspace mismatch.")
    extra: dict[str, Any] = {}
    if subdomain:
        extra["subdomain"] = subdomain
    if domain:
        extra["domain"] = domain
    try:
        url = await start_authorize(
            db,
            provider=provider,
            workspace_id=workspace_id,
            agent_id=agent_id,
            extra=extra or None,
        )
    except OAuthFlowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if (response_format or "").strip().lower() == "json":
        return JSONResponse({"authorize_url": url, "provider": provider})
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@oauth_router.get("/{provider}/callback", summary="OAuth2 callback — exchange code, encrypt tokens")
async def oauth_callback(
    provider: OAuthProvider,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if error:
        return RedirectResponse(
            url=frontend_result_url(provider=provider, status="error", message=error[:180]),
            status_code=status.HTTP_302_FOUND,
        )
    if not code or not state:
        return RedirectResponse(
            url=frontend_result_url(provider=provider, status="error", message="missing_code_or_state"),
            status_code=status.HTTP_302_FOUND,
        )
    try:
        row = await handle_callback(db, provider=provider, code=code, state=state)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        return RedirectResponse(
            url=frontend_result_url(
                provider=provider,
                status="error",
                message=quote(str(exc)[:180]),
            ),
            status_code=status.HTTP_302_FOUND,
        )
    return RedirectResponse(
        url=frontend_result_url(
            provider=provider,
            status="connected",
            connection_id=str(row.id),
        ),
        status_code=status.HTTP_302_FOUND,
    )


@oauth_router.post("/{connection_id}/disconnect", summary="Revoke provider token and mark connection revoked")
async def oauth_disconnect(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    org_id = _workspace_id(user)
    row = await get_connection_for_workspace(
        db, connection_id=connection_id, organization_id=org_id
    )
    await disconnect_connection(db, row)
    await db.commit()
    return {"status": "revoked", "connection_id": str(connection_id)}
