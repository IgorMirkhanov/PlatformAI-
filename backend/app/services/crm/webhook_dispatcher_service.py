"""Dispatch CRM partner webhooks (SSRF-safe, HMAC-signed, Celery-friendly)."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_safety import assert_safe_public_https_url
from app.repositories.crm.webhook_subscription_repository import (
    webhook_subscription_repository,
)

WEBHOOK_TIMEOUT_SECONDS = 10.0
SIGNATURE_HEADER = "X-Hub-Signature"


def sign_webhook_payload(*, secret: str, body: bytes) -> str:
    """
    Return ``sha256=<hex>`` HMAC over the raw request body.

    Header value format: ``X-Hub-Signature: sha256=<hex>``.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def build_webhook_body(event_type: str, payload: dict[str, Any]) -> bytes:
    envelope = {
        "event": event_type,
        "data": payload,
    }
    return json.dumps(envelope, separators=(",", ":"), default=str).encode("utf-8")


class WebhookDispatcherService:
    async def dispatch_event(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        POST signed payloads to every matching active subscription.

        Returns per-subscription delivery results (for logging / Celery).
        """
        subs = await webhook_subscription_repository(
            db, organization_id=organization_id
        ).list_active_for_event(event_type)
        if not subs:
            return []

        body = build_webhook_body(event_type, payload)
        results: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            timeout=WEBHOOK_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            for sub in subs:
                results.append(
                    await self._deliver_one(
                        client,
                        subscription_id=sub.id,
                        target_url=sub.target_url,
                        secret=sub.secret,
                        body=body,
                        event_type=event_type,
                    )
                )
        return results

    async def _deliver_one(
        self,
        client: httpx.AsyncClient,
        *,
        subscription_id: uuid.UUID,
        target_url: str,
        secret: str,
        body: bytes,
        event_type: str,
    ) -> dict[str, Any]:
        try:
            safe_url = assert_safe_public_https_url(target_url)
        except ValueError as exc:
            logger.warning(
                "CRM.webhook_ssrf_blocked | subscription_id={id} error={error}",
                id=subscription_id,
                error=str(exc),
            )
            return {
                "subscription_id": str(subscription_id),
                "ok": False,
                "error": f"ssrf_blocked: {exc}",
            }

        signature = sign_webhook_payload(secret=secret, body=body)
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature,
            "X-CRM-Event": event_type,
        }
        try:
            response = await client.post(safe_url, content=body, headers=headers)
            logger.info(
                "CRM.webhook_delivered | subscription_id={id} event={event} "
                "status={status} host={host}",
                id=subscription_id,
                event=event_type,
                status=response.status_code,
                host=httpx.URL(safe_url).host,
            )
            return {
                "subscription_id": str(subscription_id),
                "ok": 200 <= response.status_code < 300,
                "status_code": response.status_code,
            }
        except Exception as exc:
            logger.warning(
                "CRM.webhook_delivery_failed | subscription_id={id} error={error}",
                id=subscription_id,
                error=str(exc),
            )
            return {
                "subscription_id": str(subscription_id),
                "ok": False,
                "error": str(exc),
            }


webhook_dispatcher_service = WebhookDispatcherService()


def enqueue_partner_webhook(
    *,
    organization_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> bool:
    """
    Fire-and-forget on ``crm_actions`` Celery queue.

    Returns True when the task was accepted by the broker.
    """
    try:
        from app.tasks.crm_tasks import dispatch_webhook_task

        dispatch_webhook_task.apply_async(
            kwargs={
                "organization_id_str": str(organization_id),
                "event_type": event_type,
                "payload": payload,
            },
        )
        return True
    except Exception as exc:
        logger.debug(
            "CRM.webhook_enqueue_failed | org={org} event={event} error={error}",
            org=organization_id,
            event=event_type,
            error=str(exc),
        )
        return False


async def notify_partner_webhooks(
    db: AsyncSession,
    organization_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """
    Prefer Celery; fall back to in-process dispatch so unit tests / broker-down
    environments still exercise delivery.
    """
    if enqueue_partner_webhook(
        organization_id=organization_id,
        event_type=event_type,
        payload=payload,
    ):
        return
    try:
        await webhook_dispatcher_service.dispatch_event(
            db,
            organization_id,
            event_type,
            payload,
        )
    except Exception as exc:
        logger.warning(
            "CRM.webhook_notify_failed | org={org} event={event} error={error}",
            org=organization_id,
            event=event_type,
            error=str(exc),
        )
