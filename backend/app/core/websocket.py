from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import WebSocket
from loguru import logger


class WSEventType(str, Enum):
    NEW_MESSAGE = "NEW_MESSAGE"
    CHAT_ASSIGNED = "CHAT_ASSIGNED"
    BOT_TOGGLED = "BOT_TOGGLED"
    OPERATOR_INTERCEPT = "OPERATOR_INTERCEPT"
    STATE_UPDATED = "STATE_UPDATED"
    PING = "PING"
    PONG = "PONG"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"
    SUBSCRIBE_BOT = "SUBSCRIBE_BOT"
    UNSUBSCRIBE_BOT = "UNSUBSCRIBE_BOT"
    # Native CRM kanban (tenant-scoped via company_id / organization_id)
    CRM_DEAL_CREATED = "CRM_DEAL_CREATED"
    CRM_DEAL_UPDATED = "CRM_DEAL_UPDATED"
    CRM_DEAL_CLOSED = "CRM_DEAL_CLOSED"


@dataclass
class OperatorConnection:
    websocket: WebSocket
    operator_id: uuid.UUID
    company_id: str
    bot_rooms: set[str] = field(default_factory=set)
    connected_at: float = field(default_factory=time.monotonic)


class ConnectionManager:
    """Manages live WebSocket connections for omnichannel operator panels."""

    def __init__(self) -> None:
        self._by_operator: dict[str, set[WebSocket]] = {}
        self._by_company: dict[str, set[WebSocket]] = {}
        self._by_bot: dict[str, set[WebSocket]] = {}
        self._meta: dict[WebSocket, OperatorConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        operator_id: uuid.UUID,
        company_id: str,
    ) -> None:
        await websocket.accept()

        async with self._lock:
            operator_key = str(operator_id)
            self._meta[websocket] = OperatorConnection(
                websocket=websocket,
                operator_id=operator_id,
                company_id=company_id,
            )
            self._by_operator.setdefault(operator_key, set()).add(websocket)
            self._by_company.setdefault(company_id, set()).add(websocket)

        logger.info(
            "WS.connected | operator_id={operator_id} company_id={company_id}",
            operator_id=operator_id,
            company_id=company_id,
        )

        await self.send_to_socket(
            websocket,
            WSEventType.CONNECTED,
            {
                "operator_id": str(operator_id),
                "company_id": company_id,
                "message": "Operator channel connected.",
            },
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            meta = self._meta.pop(websocket, None)
            if meta is None:
                return

            operator_key = str(meta.operator_id)
            if operator_key in self._by_operator:
                self._by_operator[operator_key].discard(websocket)
                if not self._by_operator[operator_key]:
                    del self._by_operator[operator_key]

            if meta.company_id in self._by_company:
                self._by_company[meta.company_id].discard(websocket)
                if not self._by_company[meta.company_id]:
                    del self._by_company[meta.company_id]

            for bot_id in list(meta.bot_rooms):
                room = self._by_bot.get(bot_id)
                if not room:
                    continue
                room.discard(websocket)
                if not room:
                    del self._by_bot[bot_id]

        logger.info(
            "WS.disconnected | operator_id={operator_id}",
            operator_id=meta.operator_id if meta else None,
        )

    async def subscribe_bot(self, websocket: WebSocket, bot_id: str) -> None:
        room_key = str(bot_id)
        async with self._lock:
            meta = self._meta.get(websocket)
            if meta is None:
                return
            meta.bot_rooms.add(room_key)
            self._by_bot.setdefault(room_key, set()).add(websocket)

        logger.debug(
            "WS.subscribed_bot | operator_id={operator_id} bot_id={bot_id}",
            operator_id=meta.operator_id,
            bot_id=room_key,
        )

    async def unsubscribe_bot(self, websocket: WebSocket, bot_id: str) -> None:
        room_key = str(bot_id)
        async with self._lock:
            meta = self._meta.get(websocket)
            if meta is None:
                return
            meta.bot_rooms.discard(room_key)
            room = self._by_bot.get(room_key)
            if not room:
                return
            room.discard(websocket)
            if not room:
                del self._by_bot[room_key]

    async def send_to_socket(
        self,
        websocket: WebSocket,
        event: WSEventType,
        payload: dict[str, Any],
    ) -> None:
        try:
            await websocket.send_json({"event": event.value, "payload": payload})
        except Exception as exc:
            logger.warning("WS.send_failed | error={error}", error=str(exc))
            await self.disconnect(websocket)

    async def broadcast_to_company(
        self,
        company_id: str,
        event: WSEventType,
        payload: dict[str, Any],
    ) -> None:
        async with self._lock:
            targets = list(self._by_company.get(company_id, set()))

        if not targets:
            logger.debug(
                "WS.broadcast_skipped | company_id={company_id} event={event}",
                company_id=company_id,
                event=event.value,
            )
            return

        logger.debug(
            "WS.broadcast | company_id={company_id} event={event} targets={count}",
            company_id=company_id,
            event=event.value,
            count=len(targets),
        )

        await asyncio.gather(
            *(self.send_to_socket(socket, event, payload) for socket in targets),
            return_exceptions=True,
        )

    async def broadcast_to_bot(
        self,
        bot_id: str,
        event: WSEventType,
        payload: dict[str, Any],
    ) -> None:
        """Fan out to operators explicitly subscribed to a bot_id room."""
        room_key = str(bot_id)
        async with self._lock:
            targets = list(self._by_bot.get(room_key, set()))

        if not targets:
            return

        logger.debug(
            "WS.broadcast_bot | bot_id={bot_id} event={event} targets={count}",
            bot_id=room_key,
            event=event.value,
            count=len(targets),
        )

        await asyncio.gather(
            *(self.send_to_socket(socket, event, payload) for socket in targets),
            return_exceptions=True,
        )

    async def broadcast_live(
        self,
        company_id: str,
        event: WSEventType,
        payload: dict[str, Any],
        *,
        bot_id: str | None = None,
    ) -> None:
        """Deduped fan-out to company listeners and optional bot_id rooms."""
        async with self._lock:
            if bot_id:
                bot_targets = {
                    socket
                    for socket in self._by_bot.get(str(bot_id), set())
                    if (meta := self._meta.get(socket)) is not None
                    and meta.company_id == company_id
                }
                company_targets = set(self._by_company.get(company_id, set()))
                targets = bot_targets | company_targets
            else:
                targets = set(self._by_company.get(company_id, set()))

        if not targets:
            logger.debug(
                "WS.broadcast_live_skipped | company_id={company_id} bot_id={bot_id} event={event}",
                company_id=company_id,
                bot_id=bot_id,
                event=event.value,
            )
            return

        logger.debug(
            "WS.broadcast_live | company_id={company_id} bot_id={bot_id} event={event} targets={count}",
            company_id=company_id,
            bot_id=bot_id,
            event=event.value,
            count=len(targets),
        )

        await asyncio.gather(
            *(self.send_to_socket(socket, event, payload) for socket in targets),
            return_exceptions=True,
        )

    async def broadcast_event(
        self,
        event: WSEventType,
        payload: dict[str, Any],
    ) -> None:
        # Global fan-out is intentionally disabled — use broadcast_live with company_id.
        logger.warning(
            "WS.broadcast_event_blocked | event={event} keys={keys}",
            event=event.value,
            keys=sorted(payload.keys())[:12] if isinstance(payload, dict) else [],
        )
        return

    def active_connection_count(self) -> int:
        return len(self._meta)


connection_manager = ConnectionManager()
