"""Bot repository — tenant-filtered bot access."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.core_models import Bot
from app.models.usage import LLMUsageLog
from app.repositories.base import TenantRepository


class BotRepository(TenantRepository[Bot]):
    model = Bot
    tenant_field = "organization_id"

    def _list_options(self):
        """Eager-load relationships commonly needed by bot list UIs."""
        return (
            selectinload(Bot.flows),
            selectinload(Bot.organization),
        )

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[Bot]:
        stmt = (
            self._base_query()
            .options(*self._list_options())
            .order_by(Bot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[Bot]:
        stmt = (
            self._base_query()
            .where(Bot.user_id == user_id)
            .options(*self._list_options())
            .order_by(Bot.created_at.desc())
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def get_in_tenant(self, bot_id: uuid.UUID) -> Bot | None:
        stmt = (
            self._base_query()
            .where(Bot.id == bot_id)
            .options(*self._list_options())
        )
        return await self.session.scalar(stmt)

    async def usage_stats_by_bot(
        self,
        bot_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, float | int]]:
        """Batch aggregate LLM usage for a set of bots (avoids N+1)."""
        if not bot_ids:
            return {}
        from sqlalchemy import func

        result = await self.session.execute(
            select(
                LLMUsageLog.bot_id,
                func.count(LLMUsageLog.id).label("calls"),
                func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0).label("cost_usd"),
            )
            .where(LLMUsageLog.bot_id.in_(bot_ids))
            .group_by(LLMUsageLog.bot_id)
        )
        out: dict[uuid.UUID, dict[str, float | int]] = {}
        for bot_id, calls, cost_usd in result.all():
            if bot_id is None:
                continue
            out[bot_id] = {"calls": int(calls or 0), "cost_usd": float(cost_usd or 0.0)}
        return out


def bot_repository(
    session: AsyncSession,
    organization_id: uuid.UUID | None,
) -> BotRepository:
    return BotRepository(session, organization_id=organization_id)
