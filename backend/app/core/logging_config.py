"""Structured Loguru logging — pretty console in development, JSON in production.

Intercepts the stdlib ``logging`` root (Uvicorn / FastAPI / SQLAlchemy) into Loguru
and redacts API keys (``sk-…``, ``sk-ant-…``) from every log message.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from loguru import logger

from app.core.config import settings

REDACTED_KEY = "[REDACTED_KEY]"

# OpenAI / DeepSeek-style keys and Anthropic ``sk-ant-…``.
_API_KEY_RE = re.compile(
    r"(?i)\b("
    r"sk-ant-[A-Za-z0-9_\-]{16,}"
    r"|sk-proj-[A-Za-z0-9_\-]{16,}"
    r"|sk-[A-Za-z0-9_\-]{16,}"
    r")\b"
)

_DEV_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>{extra[correlation_id]}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def scrub_api_keys(text: str) -> str:
    """Replace OpenAI / Anthropic / DeepSeek-style API keys in free-form text."""
    if not text or "sk-" not in text.lower():
        return text
    return _API_KEY_RE.sub(REDACTED_KEY, text)


def _ensure_correlation_id(record: dict[str, Any]) -> bool:
    record["extra"].setdefault("correlation_id", "-")
    return True


def redact_secrets_filter(record: dict[str, Any]) -> bool:
    """
    Loguru filter — mutates ``record['message']`` in-place to strip secrets.

    Always returns ``True`` so records are kept after scrubbing.
    """
    _ensure_correlation_id(record)
    message = record.get("message")
    if isinstance(message, str):
        record["message"] = scrub_api_keys(message)
    # Scrub interpolated exception messages in the serialized payload path.
    exc = record.get("exception")
    if exc is not None and getattr(exc, "value", None) is not None:
        try:
            value = exc.value
            if isinstance(value, BaseException):
                scrubbed = scrub_api_keys(str(value))
                if scrubbed != str(value):
                    value.args = (scrubbed, *value.args[1:]) if value.args else (scrubbed,)
        except Exception:  # noqa: BLE001 — never break logging on scrubber bugs
            pass
    return True


class InterceptHandler(logging.Handler):
    """Route stdlib logging into Loguru (uvicorn, fastapi, sqlalchemy, …)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        message = scrub_api_keys(record.getMessage())
        logger.opt(depth=depth, exception=record.exc_info).log(level, message)


def _is_production_logging() -> bool:
    env = str(getattr(settings, "ENVIRONMENT", "development") or "development").strip().lower()
    if env in {"production", "prod"}:
        return True
    if bool(getattr(settings, "is_production", False)):
        return True
    # Explicit operator override via LOG_FORMAT=json.
    fmt = str(getattr(settings, "LOG_FORMAT", "") or "").strip().lower()
    return fmt == "json"


def setup_logging() -> None:
    """Configure Loguru sinks + stdlib interception. Safe to call multiple times."""
    logger.remove()

    level = str(getattr(settings, "LOG_LEVEL", "INFO") or "INFO").strip().upper()
    use_json = _is_production_logging()

    if use_json:
        # One-line structured JSON for aggregators (ELK / CloudWatch / Loki).
        logger.add(
            sys.stderr,
            level=level,
            serialize=True,
            backtrace=False,
            diagnose=False,
            enqueue=True,
            filter=redact_secrets_filter,
        )
        format_label = "json"
    else:
        logger.add(
            sys.stderr,
            level=level,
            format=_DEV_FORMAT,
            colorize=True,
            backtrace=True,
            diagnose=False,
            filter=redact_secrets_filter,
        )
        format_label = "pretty"

    intercept = InterceptHandler()
    logging.root.handlers = [intercept]
    logging.root.setLevel(level)

    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
        "fastapi",
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "asyncio",
        "httpx",
        "httpcore",
        "celery",
        "celery.worker",
        "celery.app.trace",
    ):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept]
        std_logger.propagate = False
        std_logger.setLevel(level)

    # Silence noisy third-party debug noise unless LOG_LEVEL is DEBUG.
    if level.upper() != "DEBUG":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger.info(
        "Logging.configured | format={fmt} level={level} env={env}",
        fmt=format_label,
        level=level,
        env=getattr(settings, "ENVIRONMENT", "development"),
    )
