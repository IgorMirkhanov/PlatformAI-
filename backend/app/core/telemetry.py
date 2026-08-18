"""Sentry SDK telemetry bootstrap for FastAPI + Celery + SQLAlchemy + Redis.

``init_telemetry()`` is a no-op when ``SENTRY_DSN`` is empty so local/dev
starts never depend on an external DSN.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.core.config import settings

REDACTED = "[REDACTED_KEY]"

# OpenAI (sk-… / sk-proj-…), Anthropic (sk-ant-…), DeepSeek-style sk- keys.
_API_KEY_RE = re.compile(
    r"(?i)\b("
    r"sk-ant-[A-Za-z0-9_\-]{20,}"
    r"|sk-proj-[A-Za-z0-9_\-]{20,}"
    r"|sk-[A-Za-z0-9_\-]{20,}"
    r")\b"
)

# Compact JWT (header.payload.signature).
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_\-]+=*\.eyJ[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-+=/]+\b"
)

# Fernet key material (url-safe base64, 32 raw bytes → 44 chars, usually ends with =).
_FERNET_KEY_RE = re.compile(r"\b[A-Za-z0-9_\-]{43}=\b")

# Fernet ciphertext tokens (often start with gAAAAA).
_FERNET_TOKEN_RE = re.compile(r"\bgAAAAA[A-Za-z0-9_\-]{20,}=*\b")

_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _API_KEY_RE,
    _JWT_RE,
    _FERNET_KEY_RE,
    _FERNET_TOKEN_RE,
)

_AUTH_HEADER_KEYS = frozenset(
    {
        "authorization",
        "Authorization",
        "X-Api-Key",
        "x-api-key",
        "X-Internal-Api-Key",
        "x-internal-api-key",
    }
)


def scrub_sensitive_text(value: str) -> str:
    """Replace known secret patterns in a free-form string."""
    scrubbed = value
    for pattern in _SENSITIVE_PATTERNS:
        scrubbed = pattern.sub(REDACTED, scrubbed)
    return scrubbed


def _scrub_headers(headers: Any) -> Any:
    if isinstance(headers, dict):
        cleaned: dict[Any, Any] = {}
        for key, value in headers.items():
            key_str = str(key)
            if key_str.lower() in {h.lower() for h in _AUTH_HEADER_KEYS} or key_str in _AUTH_HEADER_KEYS:
                cleaned[key] = REDACTED
            elif isinstance(value, str):
                cleaned[key] = scrub_sensitive_text(value)
            else:
                cleaned[key] = _scrub_value(value)
        return cleaned
    if isinstance(headers, list):
        # Sentry sometimes stores headers as [[name, value], …].
        cleaned_list: list[Any] = []
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                name, value = item[0], item[1]
                if str(name).lower() in {h.lower() for h in _AUTH_HEADER_KEYS}:
                    cleaned_list.append([name, REDACTED, *list(item[2:])])
                elif isinstance(value, str):
                    cleaned_list.append([name, scrub_sensitive_text(value), *list(item[2:])])
                else:
                    cleaned_list.append(_scrub_value(list(item)))
            else:
                cleaned_list.append(_scrub_value(item))
        return cleaned_list
    return _scrub_value(headers)


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_sensitive_text(value)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, nested in value.items():
            if str(key).lower() in {"authorization", "api_key", "apikey", "token", "password", "secret"}:
                out[key] = REDACTED
            elif str(key).lower() == "headers" or key == "headers":
                out[key] = _scrub_headers(nested)
            else:
                out[key] = _scrub_value(nested)
        return out
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    return value


def before_send_scrub_sensitive_data(
    event: dict[str, Any],
    hint: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Sentry ``before_send`` hook — redact API keys, JWTs, Fernet material and
    Authorization headers before the event leaves the process.
    """
    _ = hint
    try:
        request = event.get("request")
        if isinstance(request, dict) and "headers" in request:
            request["headers"] = _scrub_headers(request.get("headers"))

        return _scrub_value(event)  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 — never block event pipeline on scrubber bugs
        logger.warning("Telemetry.before_send_scrub_failed | error={error}", error=str(exc))
        return event


def init_telemetry() -> None:
    """
    Initialize Sentry with FastAPI / Celery / Redis / SQLAlchemy integrations.

    Safe no-op when ``SENTRY_DSN`` is unset or blank.
    """
    dsn = (getattr(settings, "SENTRY_DSN", None) or "").strip()
    environment = str(getattr(settings, "ENVIRONMENT", "development") or "development")
    log_level = str(getattr(settings, "LOG_LEVEL", "INFO") or "INFO")

    if not dsn:
        logger.debug(
            "Telemetry.sentry_disabled | reason=no_dsn env={env} log_level={level}",
            env=environment,
            level=log_level,
        )
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        logger.warning("Telemetry.sentry_skipped | reason=sentry_sdk_not_installed")
        return

    traces_sample_rate = 0.1
    profiles_sample_rate = 0.1

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=False,
        before_send=before_send_scrub_sensitive_data,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            CeleryIntegration(monitor_beat_tasks=True),
            RedisIntegration(),
            SqlalchemyIntegration(),
        ],
    )
    logger.info(
        "Telemetry.sentry_enabled | environment={env} log_level={level} "
        "traces={traces} profiles={profiles}",
        env=environment,
        level=log_level,
        traces=traces_sample_rate,
        profiles=profiles_sample_rate,
    )
