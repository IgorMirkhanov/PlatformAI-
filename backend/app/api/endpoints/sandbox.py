import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import async_session_factory, get_db
from app.core.rbac import Permission
from app.core.ws_auth import require_ws_bot_access
from app.models.core_models import Bot
from app.models.users import User
from app.schemas.sandbox_schemas import (
    SandboxChatResponse,
    SandboxClearResponse,
    SandboxMessageRequest,
    SandboxWsInbound,
    SandboxWsOutbound,
)
from app.services.execution_trace import ExecutionTraceBuilder
from app.services.sandbox_service import sandbox_service

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


def _error_outbound(
    *,
    message: str,
    session_id: str,
    error: str,
) -> dict[str, object]:
    trace = ExecutionTraceBuilder()
    trace.record_error(error)
    return SandboxWsOutbound(
        type="error",
        message=message,
        trace=trace.to_model(),
        session_id=session_id,
        error=error,
    ).model_dump(mode="json")


@router.post(
    "/{bot_id}/message",
    response_model=SandboxChatResponse,
    summary="Execute one sandbox chat turn against the published flow graph",
)
async def post_sandbox_message(
    bot_id: uuid.UUID,
    payload: SandboxMessageRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_MESSAGES)),
) -> SandboxChatResponse:
    """Invoke ``FlowExecutor`` via the published-flow cache and return a full execution trace."""
    try:
        return await sandbox_service.process_message(
            db=db,
            bot_id=bot_id,
            message_text=payload.text,
            session_id=payload.session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "SandboxHTTP.message_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sandbox flow execution failed.",
        ) from exc


@router.websocket("/{bot_id}")
async def sandbox_websocket(websocket: WebSocket, bot_id: uuid.UUID) -> None:
    """Process sandbox chat messages over WebSocket without writing production chat history."""
    async with async_session_factory() as db:
        authorized = await require_ws_bot_access(
            websocket,
            db,
            bot_id,
            Permission.BOT_MESSAGES,
        )
    if authorized is None:
        return

    await websocket.accept()
    logger.info("SandboxWS.connected | bot_id={bot_id}", bot_id=bot_id)

    try:
        while True:
            payload = await websocket.receive_json()
            session = sandbox_service.get_or_create_session(bot_id)

            try:
                inbound = SandboxWsInbound.model_validate(payload)
            except ValidationError as exc:
                await websocket.send_json(
                    _error_outbound(
                        message="Invalid sandbox payload.",
                        session_id=session.session_id,
                        error=str(exc),
                    ),
                )
                continue

            if inbound.type != "message":
                continue

            async with async_session_factory() as db:
                try:
                    result = await sandbox_service.process_message(
                        db=db,
                        bot_id=bot_id,
                        message_text=inbound.text,
                        session_id=inbound.session_id,
                    )
                    outbound = SandboxWsOutbound(
                        message=result.message,
                        trace=result.trace,
                        session_id=result.session_id,
                        current_step_id=result.current_step_id,
                        node_execution_trace=result.node_execution_trace,
                        execution_context=result.execution_context,
                        tokens_used=result.tokens_used,
                        credits_charged=result.credits_charged,
                    )
                    await websocket.send_json(outbound.model_dump(mode="json"))
                except HTTPException as exc:
                    await websocket.send_json(
                        _error_outbound(
                            message=str(exc.detail),
                            session_id=session.session_id,
                            error=str(exc.detail),
                        ),
                    )
                except Exception as exc:
                    logger.exception(
                        "SandboxWS.process_failed | bot_id={bot_id} error={error}",
                        bot_id=bot_id,
                        error=str(exc),
                    )
                    await websocket.send_json(
                        _error_outbound(
                            message="Sandbox execution failed.",
                            session_id=session.session_id,
                            error=str(exc),
                        ),
                    )
    except WebSocketDisconnect:
        logger.debug("SandboxWS.disconnected | bot_id={bot_id}", bot_id=bot_id)
    except Exception as exc:
        logger.warning(
            "SandboxWS.connection_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


@router.post(
    "/{bot_id}/clear",
    response_model=SandboxClearResponse,
    summary="Reset sandbox session state for internal testing",
)
async def clear_sandbox_session(
    bot_id: uuid.UUID,
    session_id: str | None = None,
    _bot: Bot = Depends(require_bot_access(Permission.BOT_MESSAGES)),
    db: AsyncSession = Depends(get_db),
) -> SandboxClearResponse:
    await sandbox_service._load_bot(db, bot_id)
    result = sandbox_service.clear_session(bot_id, session_id)
    return result.model_copy(update={"message": "Чат очищен. Сессия сброшена для повторного теста."})
