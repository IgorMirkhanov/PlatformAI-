"""Integrations repository — status transitions for BYOK providers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot
from app.models.integration import Integration, IntegrationStatus


class IntegrationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_for_bot(self, bot_id: uuid.UUID) -> list[Integration]:
        stmt = select(Integration).where(
            Integration.bot_id == bot_id,
            Integration.deleted_at.is_(None),
            Integration.status == IntegrationStatus.CONNECTED,
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_ai_integration(self, bot: Bot) -> Integration | None:
        integration_id = getattr(bot, "ai_integration_id", None)
        if integration_id:
            row = await self.session.get(Integration, integration_id)
            if row is not None and row.deleted_at is None:
                return row
        return None

    async def is_fallback_allowed(self, bot: Bot) -> bool:
        integration = await self.get_ai_integration(bot)
        if integration is None:
            return True
        return bool(getattr(integration, "is_fallback_allowed", True))

    async def mark_degraded(self, integration_id: uuid.UUID, error: str) -> None:
        row = await self.session.get(Integration, integration_id)
        if row is None:
            return
        row.status = IntegrationStatus.ERROR
        row.last_error = error[:2000]
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def mark_active(self, integration_id: uuid.UUID) -> None:
        row = await self.session.get(Integration, integration_id)
        if row is None:
            return
        row.status = IntegrationStatus.CONNECTED
        row.last_error = None
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
