"""WebSocket authentication helpers (JWT from query or Authorization header)."""

from __future__ import annotations

import uuid

from fastapi import WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bot_for_workspace
from app.core.auth import get_user_from_bearer
from app.core.rbac import Permission, assert_permission
from app.models.core_models import Bot, UserRole
from app.models.users import User


def extract_ws_bearer(websocket: WebSocket) -> str | None:
    """Prefer ``?token=`` / ``?access_token=``, then ``Authorization: Bearer``."""
    token = websocket.query_params.get("token") or websocket.query_params.get("access_token")
    if token:
        return token.strip()
    auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


async def authenticate_websocket_user(
    websocket: WebSocket,
    db: AsyncSession,
) -> User | None:
    token = extract_ws_bearer(websocket)
    if not token:
        return None
    x_company = websocket.query_params.get("company_id") or websocket.headers.get("x-company-id")
    return await get_user_from_bearer(db, token, x_company_id=x_company)


async def require_ws_bot_access(
    websocket: WebSocket,
    db: AsyncSession,
    bot_id: uuid.UUID,
    permission: Permission | None = None,
) -> tuple[User, Bot] | None:
    """
    Authenticate + authorize bot access for a WebSocket.

    Returns ``None`` after closing the socket on failure.
    """
    user = await authenticate_websocket_user(websocket, db)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    if permission is not None:
        try:
            assert_permission(user.role or UserRole.OPERATOR, permission)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
    try:
        bot = await get_bot_for_workspace(bot_id=bot_id, db=db, current_user=user)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    return user, bot
