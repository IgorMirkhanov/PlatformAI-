"""Integration Hub monitoring alerts (DLQ / ops hooks)."""

from __future__ import annotations

from typing import Any

from loguru import logger


def send_alert_to_monitoring(
    *,
    severity: str,
    title: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Fire an ops alert. Tests mock this; prod can wire PagerDuty/Sentry later."""
    logger.error(
        "Monitoring.alert | severity={severity} title={title} details={details}",
        severity=severity,
        title=title,
        details=details or {},
    )
