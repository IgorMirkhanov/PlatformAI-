"""Workspace tools config stored in ``bot.credentials['_mpai_workspace']``.

Holds visual Function Calling definitions and Agent RAG collections without
a dedicated table. Callers always copy-merge the credentials dict.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.core_models import Bot

WORKSPACE_KEY = "_mpai_workspace"
FUNCTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
REPORT_CHAT_ID_RE = re.compile(r"-?\d{3,20}$")
BIND_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SET_COMMAND_RE = re.compile(r"(?:^|\s)/set_([A-Za-z0-9_-]{16,64})(?:@\w+)?\b")
BIND_TTL = timedelta(minutes=30)

PARAM_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "String": "string",
    "Number": "number",
    "Boolean": "boolean",
}


def empty_workspace() -> dict[str, Any]:
    return {
        "functions": [],
        "agent_rag": [],
        "telegram_report_chats": [],
        "telegram_report_bind": None,
    }


def get_workspace(bot: Bot) -> dict[str, Any]:
    credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
    raw = credentials.get(WORKSPACE_KEY)
    if not isinstance(raw, dict):
        return empty_workspace()
    functions = raw.get("functions")
    agent_rag = raw.get("agent_rag")
    chats = raw.get("telegram_report_chats")
    bind = raw.get("telegram_report_bind")
    return {
        "functions": functions if isinstance(functions, list) else [],
        "agent_rag": agent_rag if isinstance(agent_rag, list) else [],
        "telegram_report_chats": chats if isinstance(chats, list) else [],
        "telegram_report_bind": bind if isinstance(bind, dict) else None,
    }


def set_workspace(bot: Bot, workspace: dict[str, Any]) -> None:
    credentials = dict(bot.credentials or {})
    stored = credentials.get(WORKSPACE_KEY)
    stored_chats = stored.get("telegram_report_chats") if isinstance(stored, dict) else []
    stored_bind = stored.get("telegram_report_bind") if isinstance(stored, dict) else None
    chats = (
        workspace["telegram_report_chats"]
        if "telegram_report_chats" in workspace
        else stored_chats
    )
    bind = (
        workspace["telegram_report_bind"]
        if "telegram_report_bind" in workspace
        else stored_bind
    )
    credentials[WORKSPACE_KEY] = {
        "functions": list(workspace.get("functions") or []),
        "agent_rag": list(workspace.get("agent_rag") or []),
        "telegram_report_chats": list(chats or []),
        "telegram_report_bind": bind if isinstance(bind, dict) else None,
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
    result_file = item.get("result_file") if isinstance(item.get("result_file"), dict) else {}
    integrations = [
        str(x).lower()
        for x in (item.get("result_integrations") or [])
        if x and str(x).lower() != "none"
    ]
    if result_file.get("url") or "file" in integrations:
        description = (
            f"{description} "
            "Call this function in the SAME turn whenever the user asks for photos, "
            "files, samples, or visual examples — never promise to send them later."
        ).strip()
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


def normalize_report_chat_id(value: object) -> str:
    cleaned = str(value or "").strip().replace(" ", "")
    if not REPORT_CHAT_ID_RE.fullmatch(cleaned):
        raise ValueError("ID чата должен быть числом. У группы он начинается с -100.")
    return cleaned


def apply_telegram_update_to_chats(
    chats: list[dict[str, Any]],
    update: dict[str, Any],
) -> list[dict[str, Any]]:
    """Drop a report chat when the bot is removed from it."""
    next_chats = [dict(item) for item in chats if isinstance(item, dict)]
    member = update.get("my_chat_member")
    if not isinstance(member, dict):
        return next_chats
    user = member.get("new_chat_member") if isinstance(member.get("new_chat_member"), dict) else {}
    actor = user.get("user") if isinstance(user.get("user"), dict) else {}
    if actor.get("is_bot") is False:
        return next_chats
    chat = member.get("chat") if isinstance(member.get("chat"), dict) else {}
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id or str(user.get("status") or "") not in {"left", "kicked"}:
        return next_chats
    return [item for item in next_chats if str(item.get("chat_id")) != chat_id]


def issue_telegram_report_bind(bot: Bot) -> dict[str, Any]:
    code = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + BIND_TTL).isoformat()
    workspace = get_workspace(bot)
    workspace["telegram_report_bind"] = {"code": code, "expires_at": expires_at}
    set_workspace(bot, workspace)
    return {"code": code, "command": f"/set_{code}", "expires_at": expires_at}


def claim_telegram_bind_command(bot: Bot, update: dict[str, Any]) -> str | None:
    """Bind the chat when it sends this bot's /set_ code.

    Returns the chat id when the command matched (already bound, or expired).
    Returns None when the text is not this bot's command, so a normal message
    still reaches the agent.
    """
    text, chat = _command_message(update)
    if text is None or chat is None:
        return None
    match = SET_COMMAND_RE.search(text.strip())
    if match is None:
        return None
    code = match.group(1)
    if not BIND_CODE_RE.fullmatch(code):
        return None
    workspace = get_workspace(bot)
    pending = workspace.get("telegram_report_bind")
    if not isinstance(pending, dict) or str(pending.get("code") or "") != code:
        return None
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return None
    expires = _parse_iso(pending.get("expires_at"))
    now = datetime.now(timezone.utc)
    if expires is None or expires < now:
        workspace["telegram_report_bind"] = None
        set_workspace(bot, workspace)
        return ""
    workspace["telegram_report_chats"] = _upsert_chat(
        list(workspace.get("telegram_report_chats") or []),
        chat_id=chat_id,
        title=_chat_title(chat),
    )
    workspace["telegram_report_bind"] = None
    set_workspace(bot, workspace)
    return chat_id


def upsert_telegram_report_chat(bot: Bot, *, chat_id: str, title: str, active: bool = True) -> None:
    workspace = get_workspace(bot)
    workspace["telegram_report_chats"] = _upsert_chat(
        list(workspace.get("telegram_report_chats") or []),
        chat_id=chat_id,
        title=title,
        active=active,
    )
    set_workspace(bot, workspace)


def remove_telegram_report_chat(bot: Bot, chat_id: str) -> None:
    workspace = get_workspace(bot)
    workspace["telegram_report_chats"] = [
        item
        for item in (workspace.get("telegram_report_chats") or [])
        if str(item.get("chat_id")) != chat_id
    ]
    set_workspace(bot, workspace)


def absorb_telegram_report_chat(bot: Bot, update: dict[str, Any]) -> None:
    workspace = get_workspace(bot)
    current = list(workspace.get("telegram_report_chats") or [])
    updated = apply_telegram_update_to_chats(current, update)
    if updated == current:
        return
    workspace["telegram_report_chats"] = updated
    set_workspace(bot, workspace)


def _command_message(update: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        block = update.get(key)
        if not isinstance(block, dict):
            continue
        text = block.get("text") or block.get("caption")
        chat = block.get("chat")
        if isinstance(text, str) and isinstance(chat, dict):
            return text, chat
    return None, None


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _chat_title(chat: dict[str, Any]) -> str:
    title = str(chat.get("title") or chat.get("username") or "").strip()
    return title or "Telegram-чат"


def _upsert_chat(
    chats: list[dict[str, Any]],
    *,
    chat_id: str,
    title: str,
    active: bool = True,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    for item in chats:
        if str(item.get("chat_id")) == chat_id:
            item["title"] = title or str(item.get("title") or "Telegram-чат")
            item["active"] = active
            return chats
    chats.append(
        {
            "chat_id": chat_id,
            "title": title or "Telegram-чат",
            "connected_at": now,
            "active": active,
        }
    )
    return chats
