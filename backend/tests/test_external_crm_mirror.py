"""Inbound deals are copied into a connected Bitrix or amoCRM portal."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.crm_orchestrator import crm_orchestrator


def _bot(**crm: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        credentials={"crm": crm},
    )


def test_sync_runs_only_for_a_connected_portal() -> None:
    bitrix = _bot(
        bitrix24={
            "connected": True,
            "webhook_url": "https://portal.bitrix24.kz/rest/1/secret/",
            "sync_enabled": True,
        }
    )
    amo = _bot(
        amocrm={
            "connected": True,
            "access_token": "token",
            "sync_enabled": True,
        }
    )
    plain = _bot()
    assert crm_orchestrator._is_crm_sync_enabled(bitrix, "bitrix24") is True
    assert crm_orchestrator._is_crm_sync_enabled(bitrix, "amocrm") is False
    assert crm_orchestrator._is_crm_sync_enabled(amo, "amocrm") is True
    assert crm_orchestrator._is_crm_sync_enabled(plain, "bitrix24") is False
    assert crm_orchestrator._is_crm_sync_enabled(plain, "amocrm") is False


@pytest.mark.asyncio
async def test_new_internal_deal_is_copied_to_bitrix_and_amo() -> None:
    bot = _bot(
        bitrix24={
            "connected": True,
            "webhook_url": "https://portal.bitrix24.kz/rest/1/secret/",
            "sync_enabled": True,
        },
        amocrm={
            "connected": True,
            "access_token": "token",
            "sync_enabled": True,
        },
    )
    client = SimpleNamespace(id=uuid.uuid4(), external_id="919", first_name="Анна", username="anna")
    deal = SimpleNamespace(custom_fields={})
    db = AsyncMock()
    db.get = AsyncMock(return_value=deal)
    db.flush = AsyncMock()

    with (
        patch("sqlalchemy.orm.attributes.flag_modified"),
        patch.object(
            crm_orchestrator,
            "_create_bitrix_inbound_deal",
            new=AsyncMock(return_value=501),
        ) as bitrix_create,
        patch.object(
            crm_orchestrator,
            "_create_amocrm_inbound_lead",
            new=AsyncMock(return_value=88),
        ) as amo_create,
    ):
        await crm_orchestrator._mirror_new_deal_to_external_crms(
            db,
            bot=bot,
            client=client,
            deal_id=uuid.uuid4(),
            title="Анна",
            message_text="Хочу расчёт",
            channel_type="telegram",
        )

    bitrix_create.assert_awaited_once()
    amo_create.assert_awaited_once()
    assert deal.custom_fields["bitrix_deal_id"] == "501"
    assert deal.custom_fields["amocrm_lead_id"] == "88"
    db.flush.assert_awaited_once()
