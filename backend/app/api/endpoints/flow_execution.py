"""Flow execute HTTP + streaming WebSocket API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import async_session_factory, get_db
from app.core.rbac import Permission
from app.core.ws_auth import require_ws_bot_access
from app.models.core_models import Bot
from app.models.users import User
from app.services.flow_execution_service import flow_execution_service

router = APIRouter(tags=["flow-execution"])


class ExecuteRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    use_draft: bool = False


class ExecuteResponse(BaseModel):
    session_id: str
    bot_id: uuid.UUID
    reply_text: str
    current_step_id: str
    is_waiting: bool
    nodes_visited: list[str]
    variables: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    handoff: bool = False


@router.post(
    "/bots/{bot_id}/execute",
    response_model=ExecuteResponse,
    summary="Execute one turn of the published (or draft) flow graph",
)
async def execute_bot_flow(
    bot_id: uuid.UUID,
    payload: ExecuteRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_MESSAGES)),
) -> ExecuteResponse:
    try:
        result = await flow_execution_service.execute_turn(
            db,
            bot_id=bot_id,
            message=payload.message,
            session_id=payload.session_id,
            use_draft=payload.use_draft,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        from app.services.quota_service import QuotaExceeded, quota_service

        if isinstance(exc, QuotaExceeded):
            quota_service.raise_http(exc)
        logger.exception("ExecuteAPI.failed | bot_id={bot_id}", bot_id=bot_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Flow execution failed.",
        ) from exc

    return ExecuteResponse(
        session_id=result.session_id,
        bot_id=result.bot_id,
        reply_text=result.reply_text,
        current_step_id=result.current_step_id,
        is_waiting=result.is_waiting,
        nodes_visited=result.nodes_visited,
        variables=result.variables,
        error=result.error,
        handoff=result.handoff,
    )


@router.websocket("/ws/execution/{session_id}")
async def execution_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Streaming execution channel.

    Client sends: ``{"type":"message","bot_id":"...","text":"..."}``
    Server streams: start → node_enter* → message → done | error
    """
    from app.api.deps import get_bot_for_workspace
    from app.core.rbac import assert_permission
    from app.core.ws_auth import authenticate_websocket_user
    from app.models.core_models import UserRole

    async with async_session_factory() as db:
        user = await authenticate_websocket_user(websocket, db)
        if user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()
    logger.info("ExecutionWS.connected | session_id={sid}", sid=session_id)

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await websocket.send_json({"type": "error", "error": "Invalid payload."})
                continue

            msg_type = payload.get("type") or "message"
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "session_id": session_id})
                continue

            bot_raw = payload.get("bot_id")
            text = str(payload.get("text") or payload.get("message") or "").strip()
            if not bot_raw or not text:
                await websocket.send_json(
                    {"type": "error", "error": "bot_id and text are required."}
                )
                continue

            try:
                bot_id = uuid.UUID(str(bot_raw))
            except ValueError:
                await websocket.send_json({"type": "error", "error": "Invalid bot_id."})
                continue

            async def on_event(event: dict[str, Any]) -> None:
                await websocket.send_json(event)

            async with async_session_factory() as db:
                try:
                    assert_permission(user.role or UserRole.OPERATOR, Permission.BOT_MESSAGES)
                    await get_bot_for_workspace(bot_id=bot_id, db=db, current_user=user)
                except Exception:
                    await websocket.send_json({"type": "error", "error": "Forbidden."})
                    continue
                try:
                    result = await flow_execution_service.execute_turn(
                        db,
                        bot_id=bot_id,
                        message=text,
                        session_id=session_id,
                        on_event=on_event,
                        use_draft=bool(payload.get("use_draft")),
                    )
                    await db.commit()
                    await websocket.send_json(
                        {
                            "type": "result",
                            "session_id": result.session_id,
                            "reply_text": result.reply_text,
                            "nodes_visited": result.nodes_visited,
                            "handoff": result.handoff,
                        }
                    )
                except Exception as exc:
                    logger.exception("ExecutionWS.turn_failed | sid={sid}", sid=session_id)
                    await websocket.send_json({"type": "error", "error": str(exc)})

    except WebSocketDisconnect:
        logger.info("ExecutionWS.disconnected | session_id={sid}", sid=session_id)
