"""LLM tool-calling registry used by FlowExecutor / AIOrchestrator.

Tools are optional capabilities the model may invoke mid-turn. Typed canvas
nodes (CRM, API, RAG) remain the primary control-flow mechanism.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        return [t.openai_schema() for t in self._tools.values()]

    async def invoke(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "error": f"unknown_tool:{name}"}
        try:
            return await spec.handler(arguments, context)
        except Exception as exc:
            logger.exception("ToolRegistry.invoke_failed | tool={tool} error={error}", tool=name, error=str(exc))
            return {"ok": False, "error": str(exc)}


async def _tool_rag_search(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.core.vector_db import similarity_search

    bot_id = str(context.get("bot_id") or arguments.get("knowledge_base_id") or "")
    query = str(arguments.get("query") or context.get("message") or "")
    top_k = int(arguments.get("top_k") or 3)
    if not bot_id or not query:
        return {"ok": False, "error": "bot_id_or_query_missing"}
    hits = await similarity_search(bot_id, query, top_k=top_k)
    chunks = [{"text": h} if isinstance(h, str) else {"text": str(h)} for h in (hits or [])]
    return {"ok": True, "chunks": chunks}


async def _tool_http_get(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    import httpx

    url = str(arguments.get("url") or "")
    if not url:
        return {"ok": False, "error": "url_required"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        return {
            "ok": response.is_success,
            "status": response.status_code,
            "body": response.text[:4000],
        }


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="rag_search",
            description="Search the bot knowledge base (Chroma) for relevant passages.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
            handler=_tool_rag_search,
        )
    )
    registry.register(
        ToolSpec(
            name="http_get",
            description="Perform a GET request to an allow-listed HTTP endpoint.",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            handler=_tool_http_get,
        )
    )
    return registry


def build_bot_tool_registry(bot: Any | None = None) -> ToolRegistry:
    from app.services.bot_workspace_config import function_to_openai_tool, get_workspace

    registry = build_default_tool_registry()
    if bot is None:
        return registry

    workspace = get_workspace(bot)

    async def _tool_custom(
        arguments: dict[str, Any],
        context: dict[str, Any],
        spec_item: dict[str, Any],
    ) -> dict[str, Any]:
        mode = str(spec_item.get("reaction_mode") or "llm")
        if mode == "fixed":
            return {"ok": True, "result": spec_item.get("reaction_text") or ""}
        return {
            "ok": True,
            "arguments": arguments,
            "integration": spec_item.get("integration") or "none",
        }

    for item in workspace["functions"]:
        if not isinstance(item, dict) or not item.get("is_active", True):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        mapped = function_to_openai_tool(item)
        if not mapped:
            continue
        params = mapped["function"]["parameters"]

        async def _handler(
            arguments: dict[str, Any],
            context: dict[str, Any],
            _item: dict[str, Any] = item,
        ) -> dict[str, Any]:
            return await _tool_custom(arguments, context, _item)

        registry.register(
            ToolSpec(
                name=name,
                description=str(item.get("description") or name),
                parameters=params,
                handler=_handler,
            )
        )

    for item in workspace["agent_rag"]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("function_name") or "").strip()
        if not name:
            continue

        async def _rag_handler(
            arguments: dict[str, Any],
            context: dict[str, Any],
            _item: dict[str, Any] = item,
        ) -> dict[str, Any]:
            payload = dict(arguments)
            payload["knowledge_base_id"] = str(context.get("bot_id") or "")
            result = await _tool_rag_search(payload, context)
            result["collection"] = _item.get("function_name")
            result["document_ids"] = list(_item.get("document_ids") or [])
            return result

        registry.register(
            ToolSpec(
                name=name,
                description=str(item.get("description") or f"Search knowledge collection {name}"),
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                handler=_rag_handler,
            )
        )
    return registry


default_tool_registry = build_default_tool_registry()
