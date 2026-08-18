from __future__ import annotations

import json
from typing import Any

from loguru import logger

from app.config import settings

# Canonical Redis Pub/Sub channel for operator live-chat synchronization.
OPERATOR_WS_CHANNEL = "chat_events"
# Legacy channel — subscribed only so older publishers still reach this process.
LEGACY_OPERATOR_WS_CHANNEL = "operator_ws_events"


def publish_operator_ws_event(
    *,
    company_id: str,
    event: str,
    payload: dict[str, Any],
    bot_id: str | None = None,
) -> None:
    """Publish operator WebSocket events so API servers can fan out to live connections."""
    envelope = {
        "company_id": company_id,
        "event": event,
        "payload": payload,
        "bot_id": bot_id or payload.get("bot_id"),
    }
    serialized = json.dumps(envelope)

    try:
        import redis

        client = redis.from_url(settings.REDIS_URL)
        client.publish(OPERATOR_WS_CHANNEL, serialized)
        client.close()
    except Exception as exc:
        logger.warning(
            "WSPubSub.publish_failed | company_id={company_id} event={event} error={error}",
            company_id=company_id,
            event=event,
            error=str(exc),
        )


async def run_operator_ws_subscriber() -> None:
    """Listen for worker-published events and broadcast to in-process WebSocket clients."""
    import redis.asyncio as aioredis

    from app.core.websocket import WSEventType, connection_manager

    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(OPERATOR_WS_CHANNEL, LEGACY_OPERATOR_WS_CHANNEL)
    logger.info(
        "WSPubSub.subscriber_started | channels={channels}",
        channels=[OPERATOR_WS_CHANNEL, LEGACY_OPERATOR_WS_CHANNEL],
    )

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            raw = message.get("data")
            if not raw:
                continue

            try:
                envelope = json.loads(raw)
                company_id = str(envelope["company_id"])
                event = WSEventType(str(envelope["event"]))
                payload = envelope["payload"]
                bot_id = envelope.get("bot_id") or (
                    payload.get("bot_id") if isinstance(payload, dict) else None
                )
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("WSPubSub.invalid_message | error={error}", error=str(exc))
                continue

            await connection_manager.broadcast_live(
                company_id,
                event,
                payload,
                bot_id=str(bot_id) if bot_id else None,
            )
    finally:
        await pubsub.unsubscribe(OPERATOR_WS_CHANNEL, LEGACY_OPERATOR_WS_CHANNEL)
        await pubsub.close()
        await client.close()
        logger.info("WSPubSub.subscriber_stopped")
