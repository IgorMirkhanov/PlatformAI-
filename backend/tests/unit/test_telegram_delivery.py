"""Telegram falls back to polling after a webhook the provider cannot open."""

from app.services.telegram_delivery import error_means_unreachable
from app.services.telegram_service import telegram_service


def test_connection_timeout_is_an_unreachable_webhook() -> None:
    assert error_means_unreachable("Connection timed out")
    assert error_means_unreachable("Wrong response from the webhook: 502 Bad Gateway")
    assert not error_means_unreachable("")
    assert not error_means_unreachable(None)


def test_public_webhook_uses_polling_after_a_delivery_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.telegram_delivery.webhook_delivery_blocked",
        lambda: True,
    )
    mode = telegram_service.telegram_delivery_mode(
        "https://mediacorp.kz/api/v1/webhooks/telegram/abc"
    )
    assert mode == "polling"


def test_public_webhook_stays_webhook_until_delivery_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.telegram_delivery.webhook_delivery_blocked",
        lambda: False,
    )
    mode = telegram_service.telegram_delivery_mode(
        "https://mediacorp.kz/api/v1/webhooks/telegram/abc"
    )
    assert mode == "webhook"
