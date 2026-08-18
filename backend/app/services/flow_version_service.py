"""Bot flow versioning — snapshot on publish, list, rollback."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.core_models import BotFlow
from app.models.saas_metering import BotFlowRevision


class FlowVersionService:
    async def snapshot_on_publish(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        flow: BotFlow,
        created_by: uuid.UUID | None = None,
        note: str | None = None,
    ) -> BotFlowRevision:
        next_version = await db.scalar(
            select(func.coalesce(func.max(BotFlowRevision.version), 0)).where(
                BotFlowRevision.bot_id == bot_id
            )
        )
        version = int(next_version or 0) + 1
        graph = flow.graph_data if isinstance(flow.graph_data, dict) else {}
        rev = BotFlowRevision(
            bot_id=bot_id,
            flow_id=flow.id,
            version=version,
            title=flow.title or "Untitled",
            graph_data=graph,
            created_by_user_id=created_by,
            note=note or f"Publish v{version}",
        )
        db.add(rev)
        await db.flush()
        logger.info(
            "FlowVersion.snapshot | bot_id={bot_id} version={version}",
            bot_id=bot_id,
            version=version,
        )
        return rev

    async def list_revisions(self, db: AsyncSession, bot_id: uuid.UUID) -> list[BotFlowRevision]:
        result = await db.execute(
            select(BotFlowRevision)
            .where(BotFlowRevision.bot_id == bot_id)
            .order_by(BotFlowRevision.version.desc())
        )
        return list(result.scalars().all())

    async def rollback(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        version: int,
    ) -> BotFlow:
        rev = await db.scalar(
            select(BotFlowRevision).where(
                BotFlowRevision.bot_id == bot_id,
                BotFlowRevision.version == version,
            )
        )
        if rev is None:
            raise ValueError(f"Revision v{version} not found")

        flow = await db.scalar(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        if flow is None:
            flow = await db.scalar(
                select(BotFlow).where(BotFlow.bot_id == bot_id).order_by(BotFlow.updated_at.desc()).limit(1)
            )
        if flow is None:
            raise ValueError("No flow to rollback onto")

        flow.graph_data = dict(rev.graph_data or {})
        flow.title = rev.title
        flag_modified(flow, "graph_data")
        await db.flush()
        await self.snapshot_on_publish(
            db, bot_id=bot_id, flow=flow, note=f"Rollback to v{version}"
        )
        return flow


flow_version_service = FlowVersionService()
