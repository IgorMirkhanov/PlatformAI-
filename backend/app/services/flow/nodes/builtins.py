"""Built-in message / wait / end handlers."""

from __future__ import annotations

from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
)


class MessageNodeHandler(BaseNodeHandler):
    node_types = ("message", "text", "reply", "say", "text_message")

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        text = str(ctx.data.get("text") or ctx.data.get("message") or "")
        rendered = ctx.interpolate(text)
        return NodeHandlerResult(event="message", output={"text": rendered})


class WaitingNodeHandler(BaseNodeHandler):
    node_types = ("input", "wait", "human_handoff", "question")

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        prompt = str(ctx.data.get("text") or ctx.data.get("prompt") or "")
        return NodeHandlerResult(
            event="waiting",
            waiting=True,
            output={"text": ctx.interpolate(prompt)},
        )


class EndNodeHandler(BaseNodeHandler):
    node_types = ("end", "exit", "terminate", "stop")

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        return NodeHandlerResult(event="end", terminal=True, output={})
