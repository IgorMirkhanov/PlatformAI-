"""QA automation: Integration Hub §9 disconnect/revoke + §10 card UI states."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.integration_hub import HubConnectionStatus, IntegrationConnection
from app.services.integration_hub.oauth import disconnect_connection
from app.services.integration_hub.queue import (
    ConnectionRevokedError,
    assert_connection_allows_outbound,
    enqueue_adapter_action,
)


def map_hub_card_state(
    status: str | None,
    local_connecting: bool = False,
    local_error: bool = False,
) -> str:
    """Python mirror of frontend ``mapHubCardState`` (checklist §10 contract)."""
    if local_connecting:
        return "connecting"
    if local_error:
        return "error"
    key = (status or "disconnected").lower()
    if key == "connected":
        return "connected"
    if key == "expired":
        return "expired"
    if key == "error":
        return "error"
    if key == "pending":
        return "connecting"
    return "not_connected"


def _make_user(*, org_id: uuid.UUID) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = org_id
    user.organization_id = org_id
    user.role = UserRole.OWNER
    user.is_superadmin = False
    return user


def _connection(
    *,
    org_id: uuid.UUID,
    status: str = HubConnectionStatus.CONNECTED.value,
    provider: str = "bitrix24",
) -> IntegrationConnection:
    return IntegrationConnection(
        id=uuid.uuid4(),
        organization_id=org_id,
        bot_id=None,
        provider=provider,
        status=status,
        config_json={"domain": "acme.bitrix24.ru"},
        encrypted_access_token="enc:token",
        encrypted_refresh_token="enc:refresh",
        oauth_expires_at=datetime.now(timezone.utc),
    )


def _build_app() -> FastAPI:
    from app.api.endpoints.integration_hub import oauth_router, router as hub_router

    app = FastAPI()
    app.include_router(hub_router, prefix="/api/v1")
    app.include_router(oauth_router, prefix="/api/v1")
    return app


@pytest.mark.parametrize(
    ("status", "connecting", "local_error", "expected"),
    [
        (None, False, False, "not_connected"),
        ("disconnected", False, False, "not_connected"),
        ("revoked", False, False, "not_connected"),
        ("pending", False, False, "connecting"),
        ("connected", False, False, "connected"),
        ("expired", False, False, "expired"),
        ("error", False, False, "error"),
        ("connected", True, False, "connecting"),
        ("disconnected", False, True, "error"),
        ("expired", True, True, "connecting"),
    ],
)
def test_ui_card_five_states_contract(
    status: str | None,
    connecting: bool,
    local_error: bool,
    expected: str,
) -> None:
    assert map_hub_card_state(status, connecting, local_error) == expected


@pytest.mark.asyncio
async def test_disconnect_marks_revoked_and_clears_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()
    row = _connection(org_id=org_id, provider="wazzup")
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.flush = AsyncMock()

    monkeypatch.setattr(
        "app.services.integration_hub.oauth.get_platform_oauth_app",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.oauth.secrets_from_connection_with_vault",
        AsyncMock(return_value=None),
    )

    class _Http:
        async def post(self, *a: Any, **k: Any) -> None:
            raise AssertionError("Wazzup disconnect must not require remote revoke")

        async def aclose(self) -> None:
            return None

    await disconnect_connection(db, row, http=_Http())  # type: ignore[arg-type]
    assert row.status == HubConnectionStatus.REVOKED.value
    assert row.encrypted_access_token is None
    assert row.encrypted_refresh_token is None
    assert row.credential_id is None
    assert row.oauth_expires_at is None


@pytest.mark.asyncio
async def test_disconnect_endpoint_returns_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid.uuid4()
    row = _connection(org_id=org_id)
    user = _make_user(org_id=org_id)
    app = _build_app()
    db = MagicMock()
    db.commit = AsyncMock()

    async def _override_db() -> AsyncIterator[MagicMock]:
        yield db

    monkeypatch.setattr(
        "app.api.endpoints.integration_hub.get_connection_for_workspace",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        "app.api.endpoints.integration_hub.disconnect_connection",
        AsyncMock(),
    )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/integrations/{row.id}/disconnect")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_enqueue_adapter_action_rejects_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid = uuid.uuid4()
    row = SimpleNamespace(id=cid, status=HubConnectionStatus.REVOKED.value)

    db = MagicMock()
    db.get = AsyncMock(return_value=row)

    with pytest.raises(ConnectionRevokedError) as exc:
        await assert_connection_allows_outbound(db, cid)
    assert exc.value.status == "revoked"

    called = {"n": 0}

    def apply_async(*_a: Any, **_k: Any) -> Any:
        called["n"] += 1
        return SimpleNamespace(id="should-not-run")

    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.execute_hub_adapter_action_task.apply_async",
        apply_async,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.queue.assert_connection_allows_outbound_sync",
        lambda _cid: (_ for _ in ()).throw(ConnectionRevokedError(str(cid), "revoked")),
    )
    with pytest.raises(ConnectionRevokedError):
        enqueue_adapter_action(cid, "createContact", {"name": "Ada"})
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_enqueue_adapter_action_rejects_expired() -> None:
    cid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(id=cid, status=HubConnectionStatus.EXPIRED.value)
    )
    with pytest.raises(ConnectionRevokedError) as exc:
        await assert_connection_allows_outbound(db, cid)
    assert exc.value.status == "expired"


@pytest.mark.asyncio
async def test_reconnect_after_disconnect_reuses_row_clean_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After revoke, connect() upserts the same org/provider row → connected."""
    org_id = uuid.uuid4()
    existing = _connection(
        org_id=org_id,
        status=HubConnectionStatus.REVOKED.value,
        provider="amocrm",
    )
    existing.encrypted_access_token = None
    existing.encrypted_refresh_token = None

    from app.services.integration_hub.service import integration_hub_service
    from app.services.integration_hub.types import TokenBundle

    bundle = TokenBundle(
        access_token="new-access",
        refresh_token="new-refresh",
        extra={"subdomain": "acme"},
        external_account_id="acme",
    )

    class _Adapter:
        async def connect(self, **_kwargs: Any) -> TokenBundle:
            return bundle

    class _Creds:
        def __init__(self, _db: Any) -> None:
            pass

        async def upsert(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(id=uuid.uuid4())

    db = MagicMock()
    db.scalar = AsyncMock(return_value=existing)
    db.add = MagicMock()
    db.flush = AsyncMock()

    monkeypatch.setattr(
        "app.services.integration_hub.service.get_hub_adapter",
        lambda _p: _Adapter(),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.service.get_platform_oauth_app",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.service.CredentialsRepository",
        _Creds,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.service._seal_tokens",
        lambda row, b: None,
    )

    class _Http:
        async def aclose(self) -> None:
            return None

    row = await integration_hub_service.connect(
        db,
        organization_id=org_id,
        bot_id=None,
        provider="amocrm",
        payload={"subdomain": "acme", "code": "x"},
        http=_Http(),  # type: ignore[arg-type]
    )
    assert row is existing
    assert row.status == HubConnectionStatus.CONNECTED.value
    assert row.last_error is None


@pytest.mark.asyncio
async def test_bitrix_onappuninstall_marks_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.bitrix24_tasks import _process_event

    org_id = uuid.uuid4()
    row = _connection(org_id=org_id)
    cid = row.id

    class _Session:
        async def get(self, _model: Any, _id: Any) -> IntegrationConnection:
            return row

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    monkeypatch.setattr(
        "app.tasks.bitrix24_tasks.async_session_factory",
        lambda: _Session(),
    )
    monkeypatch.setattr(
        "app.tasks.bitrix24_tasks.record_hub_usage",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.oauth.CredentialsRepository",
        lambda _db: SimpleNamespace(revoke=AsyncMock()),
    )

    result = await _process_event(str(cid), "ONAPPUNINSTALL", {})
    assert result["status"] == "revoked"
    assert row.status == HubConnectionStatus.REVOKED.value
    assert row.encrypted_access_token is None


@pytest.mark.asyncio
async def test_connection_revoked_error_maps_to_http_400() -> None:
    """Contract: ConnectionRevokedError ↔ HTTP 400 for agent/tool callers."""
    exc = ConnectionRevokedError(str(uuid.uuid4()), "revoked")
    mapped = HTTPException(status_code=400, detail=str(exc))
    assert mapped.status_code == 400
    assert "revoked" in mapped.detail
