"""CRM outbound webhook subscription CRUD."""

from __future__ import annotations

import secrets
import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_safety import assert_safe_public_https_url
from app.models.crm.webhook_subscription import CrmWebhookSubscription
from app.repositories.crm.webhook_subscription_repository import (
    webhook_subscription_repository,
)
from app.schemas.crm.webhooks import (
    CrmWebhookSubscriptionCreate,
    CrmWebhookSubscriptionCreated,
    CrmWebhookSubscriptionListResponse,
    CrmWebhookSubscriptionRead,
    CrmWebhookSubscriptionUpdate,
)


def generate_webhook_secret() -> str:
    """Cryptographically strong HMAC signing secret."""
    return secrets.token_hex(32)


class WebhookSubscriptionServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WebhookSubscriptionService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return webhook_subscription_repository(db, organization_id=organization_id)

    @staticmethod
    def _validate_target_url(url: str) -> str:
        try:
            return assert_safe_public_https_url(url)
        except ValueError as exc:
            raise WebhookSubscriptionServiceError(str(exc), status_code=400) from exc

    async def list_subscriptions(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> CrmWebhookSubscriptionListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_ordered(limit=limit, offset=offset)
        total = await repo.count_all()
        return CrmWebhookSubscriptionListResponse(
            items=[CrmWebhookSubscriptionRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_subscription(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        subscription_id: uuid.UUID,
    ) -> CrmWebhookSubscriptionRead:
        row = await self._repo(db, organization_id).get(subscription_id)
        if row is None:
            raise WebhookSubscriptionServiceError(
                "Webhook subscription not found.",
                status_code=404,
            )
        return CrmWebhookSubscriptionRead.model_validate(row)

    async def create_subscription(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmWebhookSubscriptionCreate,
    ) -> CrmWebhookSubscriptionCreated:
        safe_url = self._validate_target_url(payload.target_url)
        secret = payload.secret or generate_webhook_secret()
        entity = CrmWebhookSubscription(
            organization_id=organization_id,
            target_url=safe_url,
            event_types=list(payload.event_types),
            secret=secret,
            is_active=payload.is_active,
        )
        await self._repo(db, organization_id).add(entity)
        logger.info(
            "CRM.webhook_subscription_created | org={org} id={id} events={events}",
            org=organization_id,
            id=entity.id,
            events=entity.event_types,
        )
        return CrmWebhookSubscriptionCreated.model_validate(entity)

    async def update_subscription(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        subscription_id: uuid.UUID,
        payload: CrmWebhookSubscriptionUpdate,
    ) -> CrmWebhookSubscriptionRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(subscription_id)
        if entity is None:
            raise WebhookSubscriptionServiceError(
                "Webhook subscription not found.",
                status_code=404,
            )
        data = payload.model_dump(exclude_unset=True)
        if "target_url" in data and data["target_url"] is not None:
            data["target_url"] = self._validate_target_url(data["target_url"])
        for key, value in data.items():
            setattr(entity, key, value)
        await db.flush()
        return CrmWebhookSubscriptionRead.model_validate(entity)

    async def delete_subscription(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        subscription_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(subscription_id)
        if entity is None:
            raise WebhookSubscriptionServiceError(
                "Webhook subscription not found.",
                status_code=404,
            )
        await repo.delete(entity)


webhook_subscription_service = WebhookSubscriptionService()
