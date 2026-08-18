"""P0 hardening checks for webhooks, SSRF, flow cache, and health auth."""

from __future__ import annotations

import hashlib
import hmac
import inspect

import pytest

from app.core import webhook_auth
from app.core.config import settings
from app.core.url_safety import assert_safe_public_http_url
from app.core.flow_cache import CachedPublishedFlow, PublishedFlowCache
from app.api.endpoints import health_check, webhooks
from app.core import metrics as metrics_mod


def test_meta_signature_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    secret = "meta-test-secret"
    body = b'{"object":"whatsapp_business_account"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert webhook_auth.verify_meta_signature(body, f"sha256={digest}", app_secret=secret)
    assert not webhook_auth.verify_meta_signature(body, "sha256=deadbeef", app_secret=secret)
    assert not webhook_auth.verify_meta_signature(body, None, app_secret=secret)


def test_meta_signature_fail_closed_without_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    assert not webhook_auth.verify_meta_signature(b"{}", "sha256=abc", app_secret="")


def test_ssrf_blocks_private_hosts() -> None:
    with pytest.raises(ValueError):
        assert_safe_public_http_url("http://127.0.0.1/admin")
    with pytest.raises(ValueError):
        assert_safe_public_http_url("http://localhost/secret")
    with pytest.raises(ValueError):
        assert_safe_public_http_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError):
        assert_safe_public_http_url("http://10.0.0.5/internal")


def test_telegram_secret_compare() -> None:
    assert webhook_auth.verify_telegram_secret_token("abc", "abc")
    assert not webhook_auth.verify_telegram_secret_token("abc", "xyz")


def test_webhook_endpoints_use_auth_helpers() -> None:
    source = inspect.getsource(webhooks)
    assert "require_meta_signature" in source
    assert "verify_telegram_secret_token" in source
    assert "require_internal_service_key" in source


def test_health_and_metrics_gated() -> None:
    assert "_assert_deep_health_access" in inspect.getsource(health_check)
    assert "_assert_metrics_access" in inspect.getsource(metrics_mod)


def test_flow_cache_version_mismatch_drops_entry(monkeypatch) -> None:
    cache = PublishedFlowCache()
    import uuid
    from datetime import datetime, timezone

    bot_id = uuid.uuid4()
    entry = CachedPublishedFlow(
        flow_id=uuid.uuid4(),
        bot_id=bot_id,
        title="t",
        graph_data={},
        is_published=True,
        updated_at=datetime.now(timezone.utc),
        version="1",
    )
    cache.set(entry)
    monkeypatch.setattr(
        "app.core.redis_client.get_flow_cache_version",
        lambda _bid: "2",
    )
    assert cache.get(bot_id) is None

