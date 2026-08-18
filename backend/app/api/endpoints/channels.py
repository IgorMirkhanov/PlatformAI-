"""Omnichannel Integration Hub REST + WhatsApp QR WebSocket proxy to Baileys."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access, require_credential_access
from app.core.config import settings
from app.core.database import get_db
from app.core.rbac import Permission
from app.models.channels import HubChannelType
from app.models.core_models import Bot
from app.schemas.channel_hub_schemas import (
    ChannelConnectRequest,
    ChannelConnectResponse,
    ChannelDisconnectResponse,
    HubChannelsResponse,
)
from app.services.channels_service import channels_hub_service
from app.services.whatsapp_qr_service import whatsapp_qr_service

router = APIRouter(tags=["channels-hub"])

TIMEOUT_ERROR_PAYLOAD = {
    "success": False,
    "error": "Connection timed out. Please check your token.",
}


def _timeout_response() -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_504_GATEWAY_TIMEOUT, content=TIMEOUT_ERROR_PAYLOAD)


@router.get(
    "/bots/{bot_id}/channels",
    response_model=HubChannelsResponse,
    summary="List Omnichannel Hub statuses for all 6 channel types",
    name="list_hub_channels",
)
async def list_hub_channels(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_CHANNELS)),
) -> HubChannelsResponse:
    try:
        return await channels_hub_service.list_channels(db, bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "ChannelsHub.list_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load channel hub statuses.",
        ) from exc


@router.post(
    "/bots/{bot_id}/channels/{channel_type}/connect",
    response_model=ChannelConnectResponse,
    summary="Connect a hub channel (encrypt credentials + register webhooks)",
    responses={
        504: {
            "description": "Upstream messenger API timed out",
            "content": {
                "application/json": {
                    "example": TIMEOUT_ERROR_PAYLOAD,
                }
            },
        }
    },
)
async def connect_hub_channel(
    bot_id: uuid.UUID,
    channel_type: HubChannelType,
    payload: ChannelConnectRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_credential_access()),
) -> ChannelConnectResponse | JSONResponse:
    try:
        result = await channels_hub_service.connect_channel(db, bot_id, channel_type, payload)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError) as exc:
        await db.rollback()
        logger.warning(
            "ChannelsHub.connect_timeout | bot_id={bot_id} channel={channel} error={error}",
            bot_id=bot_id,
            channel=channel_type.value,
            error=str(exc),
        )
        return _timeout_response()
    except httpx.HTTPError as exc:
        await db.rollback()
        logger.warning(
            "ChannelsHub.connect_http_error | bot_id={bot_id} channel={channel} error={error}",
            bot_id=bot_id,
            channel=channel_type.value,
            error=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "success": False,
                "error": "Connection timed out. Please check your token."
                if "timeout" in str(exc).lower()
                else "Messenger API error: не удалось подключить канал. Для Telegram на localhost нужен polling или публичный HTTPS.",
            },
        )
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "ChannelsHub.connect_failed | bot_id={bot_id} channel={channel} error={error}",
            bot_id=bot_id,
            channel=channel_type.value,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect channel.",
        ) from exc


@router.post(
    "/bots/{bot_id}/channels/{channel_type}/disconnect",
    response_model=ChannelDisconnectResponse,
    summary="Disconnect a hub channel and purge stored credentials",
)
async def disconnect_hub_channel(
    bot_id: uuid.UUID,
    channel_type: HubChannelType,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_credential_access()),
) -> ChannelDisconnectResponse:
    try:
        result = await channels_hub_service.disconnect_channel(db, bot_id, channel_type)
        await db.commit()
        if channel_type == HubChannelType.WHATSAPP_QR:
            await whatsapp_qr_service.stop_session(bot_id)
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "ChannelsHub.disconnect_failed | bot_id={bot_id} channel={channel} error={error}",
            bot_id=bot_id,
            channel=channel_type.value,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect channel.",
        ) from exc


@router.websocket("/channels/{bot_id}/whatsapp/ws-qr")
async def whatsapp_qr_websocket(websocket: WebSocket, bot_id: uuid.UUID) -> None:
    """
    Proxy live Baileys QR frames from the Node.js whatsapp-service.

    Upstream: ``ws://{WHATSAPP_SERVICE}/ws/qr/{bot_id}``

    Important: this proxy must stay open for the full scan lifecycle and must
    not restart the Baileys session on every browser reconnect (Node keeps it).
    """
    from app.core.database import async_session_factory
    from app.core.rbac import Permission
    from app.core.ws_auth import require_ws_bot_access

    async with async_session_factory() as db:
        authorized = await require_ws_bot_access(
            websocket,
            db,
            bot_id,
            Permission.BOT_CHANNELS,
        )
    if authorized is None:
        return

    await websocket.accept()
    upstream_url = f"{settings.WHATSAPP_SERVICE_WS_URL.rstrip('/')}/ws/qr/{bot_id}"
    internal_key = (getattr(settings, "INTERNAL_SERVICE_API_KEY", None) or "").strip()
    extra_headers: dict[str, str] = {}
    if internal_key:
        extra_headers["X-Internal-Api-Key"] = internal_key
        # Query fallback for libraries that don't forward custom upgrade headers.
        sep = "&" if "?" in upstream_url else "?"
        upstream_url = f"{upstream_url}{sep}internal_key={internal_key}"
    logger.info(
        "ChannelsHub.qr_ws_proxy_start | bot_id={bot_id} upstream={url}",
        bot_id=bot_id,
        url=upstream_url.split("?")[0],
    )

    try:
        import websockets
    except ImportError as exc:
        await websocket.send_json(
            {
                "event": "connection_failed",
                "status": "failed",
                "message": "websockets package is not installed on the API server.",
                "qr_base64": None,
                "reference_id": None,
                "session_id": None,
            }
        )
        await websocket.close()
        raise RuntimeError("websockets dependency missing") from exc

    marked_connected = False

    try:
        async with websockets.connect(
            upstream_url,
            open_timeout=20,
            max_size=2_000_000,
            ping_interval=20,
            ping_timeout=20,
            additional_headers=extra_headers or None,
        ) as upstream:
            async def _pump_client_to_upstream() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        if message.get("type") == "websocket.disconnect":
                            return
                        text = message.get("text")
                        if text:
                            await upstream.send(text)
                except WebSocketDisconnect:
                    return

            client_task = asyncio.create_task(_pump_client_to_upstream())
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(upstream.recv(), timeout=90.0)
                    except asyncio.TimeoutError:
                        # Keep-alive toward browser; do not kill Baileys session.
                        try:
                            await websocket.send_json({"type": "pong", "ts": asyncio.get_event_loop().time()})
                        except Exception:
                            break
                        continue

                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")

                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Heartbeat frames from Node
                    if frame.get("type") == "pong":
                        await websocket.send_json(frame)
                        continue

                    await websocket.send_json(frame)

                    event = str(frame.get("event") or "")
                    legacy = str(frame.get("legacy_event") or "")
                    if (
                        event in {"session_connected", "CONNECTED"}
                        or legacy == "session_connected"
                    ) and not marked_connected:
                        marked_connected = True
                        await whatsapp_qr_service.mark_connected_from_frame(
                            bot_id,
                            session_id=str(frame.get("session_id") or bot_id),
                            phone=str(frame.get("reference_id") or "") or None,
                        )
                        # Keep socket briefly so the UI can settle, then exit cleanly.
                        await asyncio.sleep(1.0)
                        break
                    if event in {"connection_failed", "AUTH_FAILURE", "DISCONNECTED"}:
                        break
            finally:
                client_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client_task

    except WebSocketDisconnect:
        logger.info("ChannelsHub.qr_ws_client_disconnected | bot_id={bot_id}", bot_id=bot_id)
    except Exception as exc:
        logger.exception(
            "ChannelsHub.qr_ws_proxy_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        try:
            await websocket.send_json(
                {
                    "event": "connection_failed",
                    "status": "failed",
                    "message": (
                        "Не удалось подключиться к WhatsApp QR сервису. "
                        "Проверьте, что whatsapp-service запущен на порту 3001."
                    ),
                    "qr_base64": None,
                    "reference_id": None,
                    "session_id": str(bot_id),
                }
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
