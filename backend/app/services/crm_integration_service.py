from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot
from app.schemas.crm_schemas import (
    AmoCRMConnectRequest,
    Bitrix24ConnectRequest,
    CRMConnectResponse,
    CRMIntegrationPatchRequest,
    CRMIntegrationStatusResponse,
    CRMPipelineListResponse,
    CRMPipelineStage,
    CRMPlatformStatus,
)
from app.services.crm_orchestrator import crm_orchestrator


class CRMIntegrationService:
    async def get_status(self, db: AsyncSession, bot_id: uuid.UUID) -> CRMIntegrationStatusResponse:
        bot = await self._get_bot(db, bot_id)
        statuses = await crm_orchestrator.get_integration_status(bot)
        return CRMIntegrationStatusResponse(
            bot_id=bot_id,
            platforms=[CRMPlatformStatus.model_validate(item) for item in statuses],
        )

    async def connect_amocrm(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: AmoCRMConnectRequest,
    ) -> CRMConnectResponse:
        bot = await self._get_bot(db, bot_id)
        try:
            await crm_orchestrator.exchange_amocrm_tokens(
                db,
                bot,
                base_domain=payload.base_domain,
                client_id=payload.client_id,
                client_secret=payload.client_secret,
                authorization_code=payload.authorization_code,
                redirect_uri=payload.redirect_uri,
            )
        except Exception as exc:
            logger.exception(
                "CRMIntegration.amocrm_connect_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            raise ValueError(f"amoCRM connection failed: {exc}") from exc

        return CRMConnectResponse(
            bot_id=bot_id,
            platform="amocrm",
            connected=True,
            sync_enabled=True,
            message="amoCRM connected successfully.",
        )

    async def connect_bitrix24(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: Bitrix24ConnectRequest,
    ) -> CRMConnectResponse:
        bot = await self._get_bot(db, bot_id)
        try:
            await crm_orchestrator.connect_bitrix24(db, bot, str(payload.webhook_url))
        except Exception as exc:
            logger.exception(
                "CRMIntegration.bitrix_connect_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            raise ValueError(f"Bitrix24 connection failed: {exc}") from exc

        return CRMConnectResponse(
            bot_id=bot_id,
            platform="bitrix24",
            connected=True,
            sync_enabled=True,
            message="Bitrix24 webhook connected successfully.",
        )

    async def patch_integration(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        platform: str,
        payload: CRMIntegrationPatchRequest,
    ) -> CRMConnectResponse:
        bot = await self._get_bot(db, bot_id)
        try:
            result = await crm_orchestrator.patch_integration(
                db,
                bot,
                platform,
                payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        except Exception as exc:
            logger.exception(
                "CRMIntegration.patch_failed | bot_id={bot_id} platform={platform} error={error}",
                bot_id=bot_id,
                platform=platform,
                error=str(exc),
            )
            raise ValueError(f"Failed to update CRM integration: {exc}") from exc

        return CRMConnectResponse.model_validate(result)

    async def list_pipelines(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        platform: str,
    ) -> CRMPipelineListResponse:
        bot = await self._get_bot(db, bot_id)
        try:
            stages = await crm_orchestrator.list_pipelines(db, bot, platform)
        except Exception as exc:
            logger.exception(
                "CRMIntegration.pipelines_failed | bot_id={bot_id} platform={platform} error={error}",
                bot_id=bot_id,
                platform=platform,
                error=str(exc),
            )
            raise ValueError(f"Failed to load CRM pipelines: {exc}") from exc

        return CRMPipelineListResponse(
            bot_id=bot_id,
            platform="bitrix24" if platform.lower() == "bitrix24" else "amocrm",
            pipelines=[CRMPipelineStage.model_validate(stage) for stage in stages],
        )

    async def _get_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            raise ValueError(f"Bot with id '{bot_id}' not found.")
        return bot


crm_integration_service = CRMIntegrationService()
