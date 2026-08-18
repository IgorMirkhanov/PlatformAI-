import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission
from app.models.core_models import Bot
from app.schemas.crm_schemas import (
    AmoCRMConnectRequest,
    Bitrix24ConnectRequest,
    CRMConnectResponse,
    CRMIntegrationPatchRequest,
    CRMIntegrationStatusResponse,
    CRMPipelineListResponse,
)
from app.services.crm_integration_service import crm_integration_service

router = APIRouter(prefix="/bots", tags=["crm-integrations"])


@router.get(
    "/{bot_id}/crm/status",
    response_model=CRMIntegrationStatusResponse,
    summary="Get amoCRM and Bitrix24 connection status for a bot",
)
async def get_crm_status(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> CRMIntegrationStatusResponse:
    try:
        return await crm_integration_service.get_status(db, bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CRM.get_status_error | bot_id={bot_id} error={error}", bot_id=bot_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load CRM integration status.",
        ) from exc


@router.post(
    "/{bot_id}/crm/amocrm/connect",
    response_model=CRMConnectResponse,
    summary="Exchange amoCRM authorization code for OAuth tokens",
)
async def connect_amocrm(
    bot_id: uuid.UUID,
    payload: AmoCRMConnectRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> CRMConnectResponse:
    try:
        return await crm_integration_service.connect_amocrm(db, bot_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CRM.connect_amocrm_error | bot_id={bot_id} error={error}", bot_id=bot_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect amoCRM.",
        ) from exc


@router.post(
    "/{bot_id}/crm/bitrix24/connect",
    response_model=CRMConnectResponse,
    summary="Validate and store Bitrix24 incoming webhook URL",
)
async def connect_bitrix24(
    bot_id: uuid.UUID,
    payload: Bitrix24ConnectRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> CRMConnectResponse:
    try:
        return await crm_integration_service.connect_bitrix24(db, bot_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CRM.connect_bitrix_error | bot_id={bot_id} error={error}", bot_id=bot_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Bitrix24.",
        ) from exc


@router.get(
    "/{bot_id}/crm/pipelines",
    response_model=CRMPipelineListResponse,
    summary="Fetch CRM pipelines and stages for canvas node configuration",
)
async def list_crm_pipelines(
    bot_id: uuid.UUID,
    platform: str = Query(..., pattern="^(amocrm|bitrix24)$"),
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> CRMPipelineListResponse:
    try:
        return await crm_integration_service.list_pipelines(db, bot_id, platform)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "CRM.pipelines_error | bot_id={bot_id} platform={platform} error={error}",
            bot_id=bot_id,
            platform=platform,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load CRM pipelines.",
        ) from exc


@router.patch(
    "/{bot_id}/integrations/{crm_type}",
    response_model=CRMConnectResponse,
    summary="Update CRM credentials, sync toggle, and pipeline mapping",
)
async def patch_crm_integration(
    bot_id: uuid.UUID,
    crm_type: str,
    payload: CRMIntegrationPatchRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> CRMConnectResponse:
    if crm_type not in {"amocrm", "bitrix24"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="crm_type must be amocrm or bitrix24.",
        )
    try:
        return await crm_integration_service.patch_integration(db, bot_id, crm_type, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "CRM.patch_integration_error | bot_id={bot_id} crm_type={crm_type} error={error}",
            bot_id=bot_id,
            crm_type=crm_type,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update CRM integration.",
        ) from exc
