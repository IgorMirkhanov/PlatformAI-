"""CRM auto-capture + LLM quota / billing soft-fail tests (commercial release)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.integrations.credentials import reveal_amocrm_config, seal_amocrm_config
from app.services.ai_orchestrator import AIOrchestrator, OrchestratorResult
from app.services.crm_orchestrator import CRMOrchestrator
from app.services.quota_service import QuotaExceeded
from app.workers.crm_tasks import _capture_lead_async


@pytest.mark.asyncio
async def test_amocrm_refresh_preserves_and_reseals_tokens() -> None:
    """Refresh before expiry stores sealed access+refresh tokens in bot.credentials."""
    bot_id = uuid.uuid4()
    bot = SimpleNamespace(
        id=bot_id,
        credentials={
            "crm": {
                "amocrm": seal_amocrm_config(
                    {
                        "base_domain": "example.amocrm.ru",
                        "client_id": "cid",
                        "client_secret": "csecret",
                        "redirect_uri": "https://localhost/oauth",
                        "access_token": "old-access",
                        "refresh_token": "old-refresh",
                        "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                        "connected": True,
                    }
                )
            }
        },
    )
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    orch = CRMOrchestrator()
    with (
        patch.object(orch, "_amocrm_token_request", new=AsyncMock(return_value={
            "access_token": "new-access",
            # amoCRM sometimes omits refresh_token on rotate — must keep old.
            "expires_in": 3600,
        })),
        patch(
            "app.core.pg_locks.pg_advisory_xact_lock_uuid",
            new=AsyncMock(),
        ),
        patch.object(
            orch,
            "_get_amocrm_config",
            new=AsyncMock(
                return_value=reveal_amocrm_config(bot.credentials["crm"]["amocrm"])
            ),
        ),
    ):
        await orch._refresh_amocrm_token(
            db,
            bot,  # type: ignore[arg-type]
            reveal_amocrm_config(bot.credentials["crm"]["amocrm"]),
        )

    sealed = bot.credentials["crm"]["amocrm"]
    assert isinstance(sealed.get("access_token"), str)
    assert sealed["access_token"] != "new-access"  # still sealed ciphertext
    revealed = reveal_amocrm_config(sealed)
    assert revealed["access_token"] == "new-access"
    assert revealed["refresh_token"] == "old-refresh"
    db.commit.assert_awaited()
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_amocrm_auth_headers_refreshes_two_minutes_before_expiry() -> None:
    bot = SimpleNamespace(id=uuid.uuid4(), credentials={"crm": {"amocrm": {}}})
    config = {
        "base_domain": "example.amocrm.ru",
        "access_token": "live-token",
        "refresh_token": "r",
        "client_id": "c",
        "client_secret": "s",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
    }
    db = AsyncMock()
    orch = CRMOrchestrator()
    refresh = AsyncMock()
    with (
        patch.object(orch, "_refresh_amocrm_token", new=refresh),
        patch.object(orch, "_get_amocrm_config", new=AsyncMock(return_value={
            **config,
            "access_token": "refreshed-token",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        })),
    ):
        headers = await orch._amocrm_auth_headers(db, bot, config)  # type: ignore[arg-type]

    refresh.assert_awaited_once()
    assert headers["Authorization"] == "Bearer refreshed-token"


@pytest.mark.asyncio
async def test_capture_lead_creates_deal_for_new_client() -> None:
    """Inbound capture path: new Client → CrmContact + Deal when auto_capture is on."""
    org_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    client_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    deal_id = uuid.uuid4()
    stage_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()

    bot = SimpleNamespace(id=bot_id, organization_id=org_id)
    contact = SimpleNamespace(
        id=contact_id,
        first_name="Aigerim",
        source="telegram",
    )
    deal = SimpleNamespace(id=deal_id)
    stage = SimpleNamespace(id=stage_id, position=0)
    pipeline = SimpleNamespace(id=pipeline_id, stages=[stage])

    db = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(return_value=bot)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    contacts_repo = MagicMock()
    contacts_repo.get_by_linked_client_id = AsyncMock(return_value=None)
    pipelines_repo = MagicMock()
    pipelines_repo.get_default = AsyncMock(return_value=pipeline)
    deals_repo = MagicMock()
    deals_repo.get_latest_open_for_contact = AsyncMock(return_value=None)

    with (
        patch("app.workers.crm_tasks.async_session_factory", return_value=session_cm),
        patch(
            "app.services.crm.setting_service.setting_service.get",
            new=AsyncMock(return_value=SimpleNamespace(auto_capture_enabled=True)),
        ),
        patch(
            "app.repositories.crm.contact_repository.contact_repository",
            return_value=contacts_repo,
        ),
        patch(
            "app.services.crm.contact_service.contact_service.get_or_create_from_client",
            new=AsyncMock(return_value=contact),
        ),
        patch(
            "app.core.pg_locks.pg_advisory_xact_lock_uuid",
            new=AsyncMock(),
        ),
        patch(
            "app.repositories.crm.deal_repository.deal_repository",
            return_value=deals_repo,
        ),
        patch(
            "app.repositories.crm.pipeline_repository.pipeline_repository",
            return_value=pipelines_repo,
        ),
        patch(
            "app.services.crm.deal_service.deal_service.create_deal",
            new=AsyncMock(return_value=deal),
        ) as create_deal,
        patch(
            "app.services.crm.timeline_service.timeline_service.log_event",
            new=AsyncMock(),
        ),
    ):
        result = await _capture_lead_async(client_id, bot_id)

    assert result["success"] is True
    create_deal.assert_awaited_once()
    payload = create_deal.await_args.args[2]
    assert payload.contact_id == contact_id
    assert payload.bot_id == bot_id


@pytest.mark.asyncio
async def test_capture_lead_skips_duplicate_open_deal() -> None:
    org_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    client_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    existing_deal_id = uuid.uuid4()

    bot = SimpleNamespace(id=bot_id, organization_id=org_id)
    contact = SimpleNamespace(id=contact_id, first_name="Dup", source="telegram")
    existing_deal = SimpleNamespace(id=existing_deal_id)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(return_value=bot)
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    contacts_repo = MagicMock()
    contacts_repo.get_by_linked_client_id = AsyncMock(return_value=None)
    deals_repo = MagicMock()
    deals_repo.get_latest_open_for_contact = AsyncMock(return_value=existing_deal)

    with (
        patch("app.workers.crm_tasks.async_session_factory", return_value=session_cm),
        patch(
            "app.services.crm.setting_service.setting_service.get",
            new=AsyncMock(return_value=SimpleNamespace(auto_capture_enabled=True)),
        ),
        patch(
            "app.repositories.crm.contact_repository.contact_repository",
            return_value=contacts_repo,
        ),
        patch(
            "app.services.crm.contact_service.contact_service.get_or_create_from_client",
            new=AsyncMock(return_value=contact),
        ),
        patch("app.core.pg_locks.pg_advisory_xact_lock_uuid", new=AsyncMock()),
        patch(
            "app.repositories.crm.deal_repository.deal_repository",
            return_value=deals_repo,
        ),
        patch(
            "app.services.crm.deal_service.deal_service.create_deal",
            new=AsyncMock(),
        ) as create_deal,
    ):
        result = await _capture_lead_async(client_id, bot_id)

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["reason"] == "open_deal_already_exists"
    create_deal.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_blocked_on_zero_balance_returns_soft_message() -> None:
    """Zero wallet balance must not 500 — orchestrator returns polite fallback."""
    from app.services.ai_orchestrator import InsufficientFundsError

    orch = AIOrchestrator()
    db = AsyncMock()
    client_id = uuid.uuid4()
    bot_id = uuid.uuid4()

    with patch.object(
        orch,
        "_assert_sufficient_balance",
        new=AsyncMock(side_effect=InsufficientFundsError("balance=0")),
    ):
        result = await orch.generate_ai_response(
            db_session=db,
            client_id=client_id,
            current_node_data={"prompt_context": "You are helpful."},
            incoming_message="Привет",
            bot_id=bot_id,
        )

    assert isinstance(result, OrchestratorResult)
    assert result.text == orch.FUNDS_FALLBACK_MESSAGE
    assert "operator" in result.text.lower() or "unavailable" in result.text.lower()


@pytest.mark.asyncio
async def test_llm_blocked_on_token_quota_returns_soft_message() -> None:
    orch = AIOrchestrator()
    db = AsyncMock()
    client_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    org_id = uuid.uuid4()

    bot = SimpleNamespace(id=bot_id, organization_id=org_id)
    db.get = AsyncMock(return_value=bot)

    with (
        patch.object(orch, "_assert_sufficient_balance", new=AsyncMock()),
        patch(
            "app.services.quota_service.quota_service.assert_token_quota",
            new=AsyncMock(
                side_effect=QuotaExceeded(
                    "tokens_month_limit",
                    "Monthly token quota reached.",
                )
            ),
        ),
    ):
        result = await orch.generate_ai_response(
            db_session=db,
            client_id=client_id,
            current_node_data={"prompt_context": "You are helpful."},
            incoming_message="Привет",
            bot_id=bot_id,
        )

    assert result.text == orch.FUNDS_FALLBACK_MESSAGE


@pytest.mark.asyncio
async def test_wallet_deduct_raises_on_insufficient_without_going_negative() -> None:
    """Atomic deduct: FOR UPDATE path raises InsufficientFundsError when balance < cost."""
    from app.services.billing.wallet_service import InsufficientFundsError, WalletService

    org_id = uuid.uuid4()
    wallet = SimpleNamespace(balance=5, id=org_id)
    repo = MagicMock()
    repo.get_for_update = AsyncMock(return_value=wallet)
    repo.find_by_reference = AsyncMock(return_value=None)

    db = AsyncMock()
    svc = WalletService()
    with patch("app.services.billing.wallet_service.wallet_repository", return_value=repo):
        with pytest.raises(InsufficientFundsError) as exc_info:
            await svc.deduct_credits(
                db,
                org_id,
                amount=100,
                tx_type="llm_completion",
                reference_id="ref-1",
                auto_commit=False,
            )

    assert exc_info.value.balance == 5
    assert exc_info.value.required == 100
    assert wallet.balance == 5  # unchanged
