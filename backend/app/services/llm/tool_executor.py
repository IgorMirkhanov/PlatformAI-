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
        integrations = [
            str(item).lower()
            for item in (fn.get("result_integrations") or ([fn.get("integration")] if fn.get("integration") else []))
            if item and str(item).lower() != "none"
        ]
        result: dict[str, Any] = {
            "status": "ok",
            "function": tool_name,
            "arguments": args,
            "post_scenario": fn.get("post_scenario") or "continue",
            "disable_delayed_messages": bool(fn.get("disable_delayed_messages", False)),
            "nested_function_id": fn.get("nested_function_id"),
            "result_integrations": integrations,
            "result_fields": list(fn.get("result_fields") or []),
        }
        if str(fn.get("reaction_mode") or "llm") == "fixed":
            result["fixed_reply"] = str(fn.get("reaction_text") or "").strip()
            result["message"] = result["fixed_reply"] or f"Function '{tool_name}' executed."
        else:
            result["message"] = f"Function '{tool_name}' executed successfully."

        file_cfg = fn.get("result_file") if isinstance(fn.get("result_file"), dict) else {}
        file_url = str(file_cfg.get("url") or "").strip()
        # Send configured result file whenever a URL exists (integration tag optional).
        if file_url and ("file" in integrations or bool(file_cfg)):
            if file_url.startswith("/"):
                from app.core.config import settings

                base = (settings.WEBHOOK_BASE_URL or "").rstrip("/")
                if base:
                    file_url = f"{base}{file_url}"
            from app.services.media_dispatch_service import infer_media_kind

            caption = ""
            if str(file_cfg.get("message_mode") or "text") == "text":
                caption = str(file_cfg.get("message") or "").strip()
            result["media_attachments"] = [
                {
                    "url": file_url,
                    "media_type": infer_media_kind(
                        file_url,
                        mime_type=str(file_cfg.get("mime_type") or "") or None,
                    ),
                    "filename": str(file_cfg.get("filename") or "") or None,
                    "caption": caption or None,
                    "mime_type": str(file_cfg.get("mime_type") or "") or None,
                    "source": "function_result_file",
                }
            ]
            if "file" not in integrations:
                integrations.append("file")
                result["result_integrations"] = integrations

        if "telegram" in integrations:
            report_chat = str(fn.get("telegram_report_chat_id") or "").strip()
            if report_chat:
                result["telegram_report_chat_id"] = report_chat
                try:
                    await _send_function_telegram_report(
                        bot,
                        chat_id=report_chat,
                        tool_name=tool_name,
                        arguments=args,
                        message=str(result.get("message") or ""),
                    )
                    result["telegram_report"] = "sent"
                except Exception as exc:
                    result["telegram_report"] = "error"
                    logger.warning(
                        "ToolExecutor.telegram_report_failed | bot_id={bot_id} name={name} error={error}",
                        bot_id=bot.id,
                        name=tool_name,
                        error=str(exc),
                    )

        if "custom_api" in integrations:
            api_cfg = fn.get("custom_api") if isinstance(fn.get("custom_api"), dict) else {}
            try:
                api_result = await _call_function_custom_api(api_cfg, arguments=args)
                result["custom_api"] = api_result
            except Exception as exc:
                result["custom_api"] = {"status": "error", "message": str(exc)[:300]}
                logger.warning(
                    "ToolExecutor.custom_api_failed | bot_id={bot_id} name={name} error={error}",
                    bot_id=bot.id,
                    name=tool_name,
                    error=str(exc),
                )

        if "delayed" in integrations:
            delayed_cfg = fn.get("delayed") if isinstance(fn.get("delayed"), dict) else {}
            chat_id = str(channel_user_id or "").strip()
            client_id = str(getattr(client, "id", "") or "").strip()
            if chat_id and client_id:
                try:
                    delayed_result = _schedule_function_delayed_message(
                        bot_id=str(bot.id),
                        chat_id=chat_id,
                        client_id=client_id,
                        channel=channel,
                        config=delayed_cfg,
                        arguments=args,
                    )
                    result["delayed"] = delayed_result
                except Exception as exc:
                    result["delayed"] = {"status": "error", "message": str(exc)[:300]}
                    logger.warning(
                        "ToolExecutor.delayed_failed | bot_id={bot_id} name={name} error={error}",
                        bot_id=bot.id,
                        name=tool_name,
                        error=str(exc),
                    )
            else:
                result["delayed"] = {
                    "status": "skipped",
                    "reason": "missing_chat_or_client",
                }

        if "whatsapp" in integrations:
            group_id = str(fn.get("whatsapp_group_id") or "").strip()
            result["whatsapp_group_id"] = group_id or None
            if not group_id:
                result["whatsapp"] = {
                    "status": "skipped",
                    "reason": "group_not_configured",
                }
            else:
                # Group delivery depends on channel binding; persist target for downstream.
                result["whatsapp"] = {
                    "status": "configured",
                    "group_id": group_id,
                }

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


async def _send_function_telegram_report(
    bot: Bot,
    *,
    chat_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    message: str,
) -> None:
    from app.models.bot import get_telegram_bot_token
    from app.services.telegram_service import telegram_service

    token = get_telegram_bot_token(bot)
    lines = [f"Отчёт функции {tool_name}"]
    text = (message or "").strip()
    if text:
        lines.append(text)
    for key, value in list((arguments or {}).items())[:12]:
        rendered = str(value).replace("\n", " ").strip()
        if rendered:
            lines.append(f"{key}: {rendered[:300]}")
    await telegram_service.send_message(token, chat_id, "\n".join(lines)[:3500], [])


def _interpolate_template(template: str, arguments: dict[str, Any]) -> str:
    text = str(template or "")
    for key, value in (arguments or {}).items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
        text = text.replace(f"{{{key}}}", str(value))
    return text


def _kv_map(rows: object, arguments: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("enabled") is False:
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        value = _interpolate_template(str(row.get("value") or ""), arguments)
        out[key] = value
    return out


async def _call_function_custom_api(
    config: dict[str, Any],
    *,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    import httpx

    from app.core.url_safety import assert_safe_public_https_url

    raw_url = _interpolate_template(str(config.get("url") or "").strip(), arguments)
    if not raw_url:
        return {"status": "skipped", "reason": "url_missing"}
    safe_url = assert_safe_public_https_url(raw_url)
    method = str(config.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        method = "GET"
    params = _kv_map(config.get("params"), arguments)
    headers = _kv_map(config.get("headers"), arguments)
    body = _kv_map(config.get("body"), arguments)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.request(
            method,
            safe_url,
            params=params or None,
            headers=headers or None,
            json=body if body and method != "GET" else None,
        )

    preview = (response.text or "")[:500]
    return {
        "status": "ok" if response.is_success else "error",
        "status_code": int(response.status_code),
        "method": method,
        "url": safe_url,
        "body_preview": preview,
    }


def _schedule_function_delayed_message(
    *,
    bot_id: str,
    chat_id: str,
    client_id: str,
    channel: str,
    config: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.tasks.follow_up_task import send_function_delayed_message

    message = _interpolate_template(str(config.get("message") or "").strip(), arguments)
    if not message:
        return {"status": "skipped", "reason": "empty_message"}

    mode = str(config.get("mode") or "absolute").strip().lower()
    countdown = 300
    if mode == "relative":
        try:
            countdown = max(1, int(config.get("delay_minutes") or 5) * 60)
        except (TypeError, ValueError):
            countdown = 300
    else:
        date_s = str(config.get("date") or "").strip()
        time_s = str(config.get("time") or "00:00").strip() or "00:00"
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("Asia/Almaty")
            target = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M").replace(
                tzinfo=tz
            )
            countdown = max(1, int((target - datetime.now(tz)).total_seconds()))
        except ValueError:
            countdown = max(1, int(config.get("delay_minutes") or 5) * 60)

    async_result = send_function_delayed_message.apply_async(
        kwargs={
            "bot_id": bot_id,
            "chat_id": chat_id,
            "client_id": client_id,
            "channel": channel,
            "message": message[:3500],
        },
        countdown=countdown,
    )
    return {
        "status": "scheduled",
        "countdown": countdown,
        "task_id": async_result.id,
        "eta": (datetime.now(UTC) + timedelta(seconds=countdown)).isoformat(),
    }
