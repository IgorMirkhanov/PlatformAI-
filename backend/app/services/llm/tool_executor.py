"""Execute built-in and workspace LLM function calls."""

from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot, Client
from app.services.crm.save_lead_tool import save_lead_to_crm


BUILTIN_SAVE_LEAD_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "save_lead_to_crm",
        "description": (
            "Save a sales lead to Bitrix24 CRM. Call only when you have the user's phone "
            "number or enough identity to create a lead. On error, ask the user to re-enter data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "User phone in any format; will be normalized to E.164.",
                },
                "client_name": {
                    "type": "string",
                    "description": "User display name.",
                },
                "comment": {
                    "type": "string",
                    "description": "Optional note about the request.",
                },
            },
            "required": [],
        },
    },
}


async def execute_tool_call(
    db: AsyncSession,
    *,
    bot: Bot,
    client: Client | None,
    tool_name: str,
    arguments_json: str,
    channel: str = "web",
    channel_user_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch a single function call; returns JSON-serializable result for the LLM."""
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            args = {}
    except json.JSONDecodeError:
        args = {}

    if tool_name == "save_lead_to_crm":
        return await save_lead_to_crm(
            db,
            bot=bot,
            client=client,
            phone=args.get("phone"),
            client_name=args.get("client_name"),
            comment=args.get("comment"),
            channel=channel,
            channel_user_id=channel_user_id,
        )

    logger.warning("ToolExecutor.unknown_tool | name={name}", name=tool_name)
    return {"status": "error", "reason": "unknown_tool", "message": f"Unknown tool: {tool_name}"}


def parse_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Extract OpenAI-style tool_calls from a chat completion message object."""
    raw = getattr(message, "tool_calls", None) or []
    parsed: list[dict[str, Any]] = []
    for call in raw:
        fn = getattr(call, "function", None)
        if fn is None:
            continue
        parsed.append(
            {
                "id": getattr(call, "id", None),
                "name": str(getattr(fn, "name", "") or ""),
                "arguments": str(getattr(fn, "arguments", "") or "{}"),
            }
        )
    return parsed
