"""Trigger node — graph entry / session variable bootstrap."""

from __future__ import annotations

from typing import Any

from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
)


class TriggerNodeHandler(BaseNodeHandler):
    node_types = ("trigger", "start", "entry")

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        inbound = ctx.initial_input or {}
        # Prefer nested inbound DTO-like payload when present.
        payload = inbound.get("inbound") if isinstance(inbound.get("inbound"), dict) else inbound

        sender_id = (
            payload.get("sender_id")
            or payload.get("from")
            or inbound.get("sender_id")
        )
        message_text = (
            payload.get("content")
            or payload.get("message_text")
            or payload.get("text")
            or inbound.get("message")
            or inbound.get("__message__")
        )
        channel = payload.get("channel") or inbound.get("channel")

        if sender_id is not None:
            ctx.variables["sender_id"] = str(sender_id)
        if message_text is not None:
            ctx.variables["message_text"] = str(message_text)
            ctx.variables["last_input"] = str(message_text)
        if channel is not None:
            ctx.variables["channel"] = str(channel)

        # Merge remaining scalar bootstrap keys.
        for key, value in inbound.items():
            if str(key).startswith("__") or key in {"inbound", "message", "__message__"}:
                continue
            if isinstance(value, (dict, list)):
                continue
            ctx.variables.setdefault(str(key), value)

        return NodeHandlerResult(
            event="triggered",
            output={
                "sender_id": ctx.variables.get("sender_id"),
                "message_text": ctx.variables.get("message_text"),
            },
        )
