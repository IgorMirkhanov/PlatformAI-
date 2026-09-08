"""Smoke tests for Integrations + Channels catalog expansion."""

from __future__ import annotations

import inspect

from app.models.channels import HUB_CHANNEL_TYPES, HubChannelType
from app.services.bot_app_integrations_service import (
    INTEGRATION_PLATFORMS,
    bot_app_integrations_service,
)
from app.api.endpoints import bot_app_integrations, webhooks
from app.services import channels_service
from app.services.ocr_service import parse_kaspi_receipt_text


def test_integration_catalog_has_screenshot_platforms() -> None:
    expected = {
        "amocrm",
        "kommo",
        "bitrix24",
        "google_calendar",
        "google_sheets",
        "kaspi_receipts",
        "kaspi_pay",
        "custom_webhook",
        "jivo",
        "uon",
    }
    assert set(INTEGRATION_PLATFORMS) == expected


def test_hub_channels_has_nine_types() -> None:
    values = {item.value for item in HUB_CHANNEL_TYPES}
    assert values >= {
        "telegram",
        "telegram_business",
        "wazzup",
        "whatsapp_qr",
        "instagram",
        "waba",
        "calls",
        "api",
        "web_widget",
    }
    assert HubChannelType.WEB_WIDGET in HUB_CHANNEL_TYPES


def test_connect_methods_exist_for_new_channels() -> None:
    source = inspect.getsource(channels_service.ChannelsHubService.connect_channel)
    assert "WEB_WIDGET" in source
    assert "API" in source
    assert "CALLS" in source
    assert "GREENAPI" in source


def test_webhook_routes_cover_new_ingress() -> None:
    source = inspect.getsource(webhooks)
    assert "/webhooks/jivo/" in source
    assert "/webhooks/widget/" in source
    assert "/webhooks/api/" in source
    assert "/webhooks/calls/" in source


def test_app_integrations_router_mounted() -> None:
    paths = [getattr(r, "path", "") for r in bot_app_integrations.router.routes]
    assert any("app-integrations" in p for p in paths)


def test_kaspi_receipt_text_parser() -> None:
    data = parse_kaspi_receipt_text(
        "Kaspi Gold\nНомер перевода: 123456789012\nСумма: 1 500,00 ₸"
    )
    assert data.transaction_id == "123456789012"
    assert data.amount is not None
    assert data.is_complete


def test_status_labels_cover_catalog() -> None:
    class _Bot:
        credentials = {}

    bot = _Bot()
    for platform in INTEGRATION_PLATFORMS:
        status = bot_app_integrations_service._status_for(bot, platform)  # type: ignore[arg-type]
        assert status["platform"] == platform
        assert status["label"]

