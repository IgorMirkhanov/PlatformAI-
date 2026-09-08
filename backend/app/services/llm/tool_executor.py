"""Execute built-in and workspace LLM function calls."""

from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot, Client
from app.services.crm.save_lead_tool import save_lead_to_crm
from app.services.integrations.google_calendar_service import check_calendar_availability as gcal_check_availability
from app.services.bot_app_integrations_service import bot_app_integrations_service


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


BUILTIN_CALENDAR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_calendar_availability",
            "description": "Check Google Calendar free/busy slots for the agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_iso": {"type": "string"},
                    "end_iso": {"type": "string"},
                },
                "required": ["start_iso", "end_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Book a meeting in Google Calendar for the client.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_iso": {"type": "string"},
                    "end_iso": {"type": "string"},
                    "client_email": {"type": "string"},
                    "client_phone": {"type": "string"},
                },
                "required": ["title", "start_iso", "end_iso"],
            },
        },
    },
]


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

    if tool_name == "check_calendar_availability":
        from app.services.bot_app_integrations_service import _reveal_block

        config = _reveal_block(
            "google_calendar",
            bot_app_integrations_service._read_integration(bot, "google_calendar"),
        )
        if not config.get("connected"):
            return {"status": "error", "message": "Google Calendar is not connected."}
        return await gcal_check_availability(
            bot,
            start_iso=str(args.get("start_iso") or ""),
            end_iso=str(args.get("end_iso") or ""),
            config=config,
        )

    if tool_name == "create_calendar_event":
        return await bot_app_integrations_service.create_calendar_event(
            bot,
            summary=str(args.get("title") or "Meeting"),
            start_iso=str(args.get("start_iso") or ""),
            end_iso=str(args.get("end_iso") or ""),
            attendee_email=args.get("client_email"),
            client_phone=args.get("client_phone"),
        )

    # Workspace custom functions (Function Calling constructor).
    from app.services.bot_workspace_config import get_workspace

    workspace = get_workspace(bot)
    for fn in workspace.get("functions") or []:
        if not isinstance(fn, dict):
            continue
        if str(fn.get("name") or "") != tool_name:
            continue
        if not bool(fn.get("is_active", True)):
            return {"status": "error", "message": f"Function '{tool_name}' is disabled."}
        result: dict[str, Any] = {
            "status": "ok",
            "function": tool_name,
            "arguments": args,
            "post_scenario": fn.get("post_scenario") or "continue",
            "disable_delayed_messages": bool(fn.get("disable_delayed_messages", False)),
            "nested_function_id": fn.get("nested_function_id"),
            "result_integrations": list(fn.get("result_integrations") or []),
            "result_fields": list(fn.get("result_fields") or []),
        }
        if str(fn.get("reaction_mode") or "llm") == "fixed":
            result["fixed_reply"] = str(fn.get("reaction_text") or "").strip()
            result["message"] = result["fixed_reply"] or f"Function '{tool_name}' executed."
        else:
            result["message"] = f"Function '{tool_name}' executed successfully."
        logger.info(
            "ToolExecutor.workspace_fn | bot_id={bot_id} name={name}",
            bot_id=bot.id,
            name=tool_name,
        )
        return result

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
