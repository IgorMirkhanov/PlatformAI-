"""Operator live-chat WebSocket feed broadcaster.

Maintains high-speed WebSocket loops for operator dashboard sessions and fans
out Redis `chat_events` payloads (inbound webhook messages, intercept state).
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from loguru import logger

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.websocket import WSEventType, connection_manager
from app.core.ws_auth import authenticate_websocket_user, extract_ws_bearer
from app.models.core_models import Bot
from app.services.chat_service import resolve_operator_company

router = APIRouter(tags=["operator-websocket"])


def _legacy_operator_token_ok(token: str | None) -> bool:
    """Dev-only shared token fallback (disabled in production)."""
    if settings.is_production or not token:
        return False
    return token == settings.OPERATOR_WS_TOKEN


@router.websocket("/ws/operator/{operator_id}")
async def operator_websocket(
    websocket: WebSocket,
    operator_id: uuid.UUID,
    token: str | None = Query(default=None),
) -> None:
    """Persistent operator feed loop with optional per-bot room subscriptions."""
    company_id = "default"
    async with async_session_factory() as db:
        user = await authenticate_websocket_user(websocket, db)
        if user is None and _legacy_operator_token_ok(token or extract_ws_bearer(websocket)):
            # Legacy shared-secret path (development only).
            company_id = await resolve_operator_company(db, operator_id)
        elif user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            logger.warning(
                "WS.auth_failed | operator_id={operator_id}",
                operator_id=operator_id,
            )
            return
        else:
            if user.id != operator_id and not (
                getattr(user, "is_superadmin", False) or getattr(user, "is_support", False)
            ):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                logger.warning(
                    "WS.operator_mismatch | path={path} jwt_sub={sub}",
                    path=operator_id,
                    sub=user.id,
                )
                return
            operator_id = user.id
            company_id = (
                str(user.company_id) if getattr(user, "company_id", None) else str(user.id)
            )

    await connection_manager.connect(
        websocket=websocket,
        operator_id=operator_id,
        company_id=company_id,
    )

    heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket))

    try:
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}

            if event == WSEventType.PING.value:
                await connection_manager.send_to_socket(
                    websocket,
                    WSEventType.PONG,
                    {"timestamp": payload.get("timestamp")},
                )
                continue

            if event == WSEventType.SUBSCRIBE_BOT.value:
                bot_id = payload.get("bot_id")
                if bot_id:
                    # Tenant-scope bot subscriptions — no "default" wildcard.
                    try:
                        bot_uuid = uuid.UUID(str(bot_id))
                    except ValueError:
                        continue
                    async with async_session_factory() as db:
                        bot = await db.get(Bot, bot_uuid)
                        if bot is None:
                            continue
                        allowed = {
                            str(bot.organization_id) if bot.organization_id else None,
                            str(bot.user_id) if bot.user_id else None,
                        }
                        allowed.discard(None)
                        if company_id not in allowed:
                            logger.warning(
                                "WS.subscribe_denied | bot={bot} company={company}",
                                bot=bot_id,
                                company=company_id,
                            )
                            continue
                    await connection_manager.subscribe_bot(websocket, str(bot_id))
                continue

            if event == WSEventType.UNSUBSCRIBE_BOT.value:
                bot_id = payload.get("bot_id")
                if bot_id:
                    await connection_manager.unsubscribe_bot(websocket, str(bot_id))
                continue
    except WebSocketDisconnect:
        logger.debug("WS.client_disconnect | operator_id={operator_id}", operator_id=operator_id)
    except Exception as exc:
        logger.warning(
            "WS.connection_error | operator_id={operator_id} error={error}",
            operator_id=operator_id,
            error=str(exc),
        )
    finally:
        heartbeat_task.cancel()
        await connection_manager.disconnect(websocket)


async def _heartbeat_loop(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(settings.WS_HEARTBEAT_INTERVAL)
            await connection_manager.send_to_socket(
                websocket,
                WSEventType.PING,
                {},
            )
    except asyncio.CancelledError:
        return
    except Exception:
        return
