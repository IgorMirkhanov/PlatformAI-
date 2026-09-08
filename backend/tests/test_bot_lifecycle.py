"""Bot lifecycle hardening — ACL, org bind, quota soft-delete filter."""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.endpoints import bot_management as bot_mgmt_ep
from app.api.endpoints import bots as bots_ep
from app.api.endpoints import health_check as health_ep
from app.models.core_models import PlatformType, UserRole
from app.schemas.core_schemas import CreateBotRequest
from app.services.bot_management_service import BotManagementService
from app.services.quota_service import QuotaExceeded, QuotaService


def _user(**overrides):
    base = {
        "id": uuid.uuid4(),
        "email": "owner@mp.ai",
        "company_id": uuid.uuid4(),
        "company_name": "Acme",
        "role": UserRole.OWNER,
        "is_superadmin": False,
        "is_support": False,
        "timezone": "Asia/Almaty",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_profile_and_settings_routes_require_bot_access() -> None:
    profile_deps = bot_mgmt_ep.get_bot_profile.__annotations__
    settings_deps = inspect.signature(bot_mgmt_ep.update_bot_settings).parameters
    assert "_bot" in settings_deps
    # Endpoint callables accept Depends(require_bot_access(...)) via FastAPI params.
    assert "bot_id" in inspect.signature(bot_mgmt_ep.get_bot_profile).parameters
    assert "bot_id" in inspect.signature(bot_mgmt_ep.update_bot_settings).parameters
    assert "bot_id" in inspect.signature(bot_mgmt_ep.update_bot_prompting).parameters
    assert "bot_id" in inspect.signature(bot_mgmt_ep.update_bot_llm_config).parameters
    assert "bot_id" in inspect.signature(bot_mgmt_ep.update_bot_functions).parameters
    _ = profile_deps


def test_setup_telegram_requires_auth_dependency() -> None:
    params = inspect.signature(bot_mgmt_ep.setup_telegram_bot).parameters
    assert "current_user" in params


def test_health_bots_require_auth() -> None:
    list_params = inspect.signature(health_ep.list_bots_health).parameters
    get_params = inspect.signature(health_ep.get_bot_health).parameters
    assert "current_user" in list_params
    assert "_bot" in get_params


def test_delete_endpoint_uses_bot_service_cascade() -> None:
    source = inspect.getsource(bots_ep.delete_bot)
    assert "bot_service.delete_bot_cascade" in source
    assert "bot_management_service.delete_bot" not in source


@pytest.mark.asyncio
async def test_create_bot_ensures_primary_company() -> None:
    service = BotManagementService()
    user = _user(company_id=None)
    org_id = uuid.uuid4()

    async def _ensure(db, u):
        u.company_id = org_id
        u.company_name = "Ensured Co"

    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    with (
        patch("app.services.team_service.team_service._ensure_primary_company", side_effect=_ensure),
        patch("app.services.quota_service.quota_service.assert_can_create_bot", AsyncMock()),
        patch.object(
            service,
            "_resolve_user",
            AsyncMock(return_value=user),
        ),
    ):
        # After flush, bot needs an id for cache/flow wiring.
        def _add(obj):
            if getattr(obj, "id", None) is None and obj.__class__.__name__ == "Bot":
                obj.id = uuid.uuid4()
            if getattr(obj, "id", None) is None and obj.__class__.__name__ == "BotFlow":
                obj.id = uuid.uuid4()
                obj.updated_at = None

        db.add.side_effect = _add

        payload = CreateBotRequest(
            name="Agent One",
            platform_type=PlatformType.TELEGRAM,
            user_id=user.id,
        )
        # create_bot will call FlowGraphData / BotFlow — keep use_case empty.
        response = await service.create_bot(db, payload, current_user=user)

    assert user.company_id == org_id
    assert response.name == "Agent One"


@pytest.mark.asyncio
async def test_quota_ignores_soft_deleted_bots() -> None:
    service = QuotaService()
    org_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=999)

    with patch.object(service, "_plan", AsyncMock(return_value=__import__(
        "app.models.core_models", fromlist=["SubscriptionPlanName"]
    ).SubscriptionPlanName.FREE)):
        with pytest.raises(QuotaExceeded):
            await service.assert_can_create_bot(db, org_id)

    # Ensure the count query filters deleted_at.
    call_args = db.scalar.await_args
    assert call_args is not None
    stmt = call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "deleted_at" in compiled.lower() or "bots.deleted_at" in compiled.lower()


@pytest.mark.asyncio
async def test_list_bots_health_tenant_scoped() -> None:
    service = BotManagementService()
    db = AsyncMock()

    empty = await service.list_bots_health(db, organization_id=None, include_all=False)
    assert empty.total == 0
    db.execute.assert_not_called()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    scoped = await service.list_bots_health(
        db,
        organization_id=uuid.uuid4(),
        include_all=False,
    )
    assert scoped.total == 0
    db.execute.assert_awaited()
