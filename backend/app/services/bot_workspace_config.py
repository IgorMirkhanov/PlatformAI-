"""Workspace tools config stored in ``bot.credentials['_mpai_workspace']``.

Holds visual Function Calling definitions and Agent RAG collections without
a dedicated table. Callers always copy-merge the credentials dict.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.models.core_models import Bot

WORKSPACE_KEY = "_mpai_workspace"
FUNCTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

PARAM_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "String": "string",
    "Number": "number",
    "Boolean": "boolean",
}


def empty_workspace() -> dict[str, Any]:
    return {"functions": [], "agent_rag": []}


def get_workspace(bot: Bot) -> dict[str, Any]:
    credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
    raw = credentials.get(WORKSPACE_KEY)
    if not isinstance(raw, dict):
        return empty_workspace()
    functions = raw.get("functions")
    agent_rag = raw.get("agent_rag")
    return {
        "functions": functions if isinstance(functions, list) else [],
        "agent_rag": agent_rag if isinstance(agent_rag, list) else [],
    }


def set_workspace(bot: Bot, workspace: dict[str, Any]) -> None:
    credentials = dict(bot.credentials or {})
    credentials[WORKSPACE_KEY] = {
        "functions": list(workspace.get("functions") or []),
        "agent_rag": list(workspace.get("agent_rag") or []),
    }
    bot.credentials = credentials
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(bot, "credentials")


def validate_function_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not FUNCTION_NAME_RE.fullmatch(cleaned):
        raise ValueError(
            "Function name must start with a letter and contain only Latin letters, digits, and underscore."
        )
    return cleaned


def function_to_openai_tool(item: dict[str, Any]) -> dict[str, Any] | None:
    if not item.get("is_active", True):
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in item.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        pname = str(param.get("name") or "").strip()
        if not pname:
            continue
        ptype = PARAM_TYPE_MAP.get(str(param.get("type") or "string"), "string")
        instruction = str(param.get("instruction") or "").strip()
        properties[pname] = {"type": ptype, "description": instruction}
        if param.get("required"):
            required.append(pname)
    description = str(item.get("description") or "").strip() or f"Call {name}"
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def agent_rag_to_openai_tool(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(item.get("function_name") or "").strip()
    if not name:
        return None
    description = str(item.get("description") or "").strip() or (
        f"Search knowledge base '{name}' when the user question matches this collection."
    )
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for this knowledge collection.",
                    }
                },
                "required": ["query"],
            },
        },
    }


def openai_tools_for_bot(bot: Bot, *, include_crm: bool = True) -> list[dict[str, Any]]:
    from app.services.llm.tool_executor import BUILTIN_SAVE_LEAD_TOOL

    workspace = get_workspace(bot)
    tools: list[dict[str, Any]] = []
    if include_crm:
        crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
        bitrix = crm.get("bitrix24") if isinstance(crm, dict) else {}
        if isinstance(bitrix, dict) and bitrix.get("connected"):
            tools.append(BUILTIN_SAVE_LEAD_TOOL)
    for item in workspace["functions"]:
        if isinstance(item, dict):
            mapped = function_to_openai_tool(item)
            if mapped:
                tools.append(mapped)
    for item in workspace["agent_rag"]:
        if isinstance(item, dict):
            mapped = agent_rag_to_openai_tool(item)
            if mapped:
                tools.append(mapped)
    return tools


def new_id() -> str:
    return str(uuid.uuid4())
