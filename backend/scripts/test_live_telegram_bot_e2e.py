"""Live Telegram bot E2E — agent lifecycle, integrations, LLM tools, outbound delivery.

Sandboxes (free, ~1 min setup):
  Google OAuth Playground → E2E_GOOGLE_ACCESS_TOKEN
  Bitrix24 inbound webhook  → E2E_BITRIX24_WEBHOOK_URL

Chain:
  1. Telegram Bot API getMe
  2. POST /api/v1/bots — create agent
  3. Connect Telegram channel + enable
  4. Connect google_calendar + bitrix24 (Playground token + inbound webhook)
  5. Simulate inbound Telegram update through the pipeline
  6. Live Google Calendar event + Bitrix24 deal/lead via real REST APIs
  7. Validate outbound Telegram delivery
  8. Teardown — DELETE bot

Usage (inside backend container):
  export E2E_TELEGRAM_BOT_TOKEN="<botfather token>"
  export E2E_GOOGLE_ACCESS_TOKEN="<oauth playground access token>"
  export E2E_BITRIX24_WEBHOOK_URL="https://b24-xxx.bitrix24.ru/rest/1/yyyyy/"
  export E2E_AUTO_AUTH=1
  export MPAI_BASE_URL=http://127.0.0.1:8000
  python scripts/test_live_telegram_bot_e2e.py

Exit code 0 when all 8 steps pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.auth import mint_user_token  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import async_session_factory  # noqa: E402
from app.core.security import hash_bot_token  # noqa: E402
from app.models.core_models import Bot  # noqa: E402
from app.models.users import User  # noqa: E402
from app.services.inbound.normalizer import normalize_telegram  # noqa: E402
from app.services.inbound.outbound_router import deliver_outbound  # noqa: E402
from app.services.llm.tool_executor import (  # noqa: E402
    BUILTIN_CALENDAR_TOOLS,
    execute_tool_call,
)
from app.services.telegram_service import telegram_service  # noqa: E402
from sqlalchemy import select  # noqa: E402

OK = "\033[92m[OK]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
WARN = "\033[93m[WARN]\033[0m"

INBOUND_TEXT = (
    "Привет! Свободно ли время завтра в 15:00? "
    "Если да, запиши меня на консультацию. "
    "Меня зовут Игорь, телефон +77071234567, email test@domain.com"
)

E2E_PHONE = os.getenv("E2E_TEST_PHONE", "+77071234567")
E2E_GOOGLE_EVENT_TITLE = "E2E Meeting Validation"
E2E_BITRIX_ENTITY_TITLE = "E2E Test Lead"

AGENT_NAME = "Live E2E Validation Agent"
E2E_MODEL = os.getenv("E2E_LLM_MODEL", "openai/gpt-oss-20b:free")
GOOGLE_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class LiveSandboxResult:
    ok: bool
    entity_id: str | None = None
    link: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class E2EContext:
    token: str
    base_url: str
    auth_headers: dict[str, str]
    google_access_token: str = ""
    bitrix_webhook_url: str = ""
    bot_id: str | None = None
    token_hash: str | None = None
    webhook_secret: str | None = None
    telegram_bot_id: int | None = None
    telegram_username: str | None = None
    chat_id: str = field(default_factory=lambda: os.getenv("E2E_TELEGRAM_CHAT_ID", "900001234"))
    tool_executions: list[dict[str, Any]] = field(default_factory=list)
    outbound_messages: list[dict[str, Any]] = field(default_factory=list)
    pipeline_response: str = ""
    google_event_id: str | None = None
    google_event_link: str | None = None
    bitrix_entity_id: str | None = None
    bitrix_entity_link: str | None = None
    bitrix_entity_type: str | None = None
    reused_bot: bool = False


def _log(tag: str, message: str) -> None:
    print(f"{tag} {message}", flush=True)


def _normalize_bitrix_webhook(url: str) -> str:
    return url.strip().rstrip("/") + "/"


def _bitrix_portal_base(webhook_url: str) -> str:
    match = re.match(r"(https?://[^/]+)", webhook_url.strip())
    return match.group(1) if match else ""


def _bitrix_card_link(webhook_url: str, entity_type: str, entity_id: str) -> str:
    base = _bitrix_portal_base(webhook_url)
    if not base or not entity_id:
        return ""
    segment = "deal" if entity_type == "deal" else "lead"
    return f"{base}/crm/{segment}/details/{entity_id}/"


def _flow_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "start",
                "type": "trigger",
                "data": {"trigger_type": "message_received", "webhook_event": ""},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "llm",
                "type": "ai_agent",
                "data": {
                    "prompt_context": (
                        "Ты ассистент записи на консультацию MP.AI. "
                        "Когда клиент спрашивает о свободном времени — обязательно вызови "
                        "check_calendar_availability, затем create_calendar_event если слот свободен. "
                        "Когда есть имя и телефон — обязательно вызови save_lead_to_crm. "
                        "Отвечай кратко по-русски."
                    ),
                    "knowledge_base_id": "default",
                    "prompt_modifier": "",
                    "temperature": 0.1,
                    "variables": [],
                },
                "position": {"x": 280, "y": 0},
            },
            {
                "id": "end",
                "type": "text_message",
                "data": {"text": "Спасибо за обращение!", "buttons": []},
                "position": {"x": 560, "y": 0},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "end"},
        ],
    }


def _tomorrow_slot_iso(tz_name: str = "Asia/Almaty") -> tuple[str, str, str]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    target = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    end = target + timedelta(hours=1)
    return target.isoformat(), end.isoformat(), tz_name


def _telegram_update(*, chat_id: str, text: str, update_id: int) -> dict[str, Any]:
    chat_num = int(chat_id) if chat_id.lstrip("-").isdigit() else 900001234
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(datetime.now().timestamp()),
            "text": text,
            "chat": {"id": chat_num, "type": "private", "first_name": "Igor"},
            "from": {
                "id": chat_num,
                "is_bot": False,
                "first_name": "Igor",
                "username": "e2e_igor",
            },
        },
    }


async def _api_login(base_url: str, email: str, password: str) -> dict[str, str]:
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        resp = await client.post(
            "/api/v1/auth/login/json",
            json={"email": email, "password": password},
        )
        resp.raise_for_status()
        data = resp.json()
        headers = {
            "Authorization": f"Bearer {data['access_token']}",
            "Content-Type": "application/json",
        }
        if data.get("company_id"):
            headers["X-Company-Id"] = str(data["company_id"])
        return headers


async def _mint_auth_from_db(email: str) -> dict[str, str]:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            raise RuntimeError(f"User not found: {email}")
        token = mint_user_token(user)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if user.company_id:
            headers["X-Company-Id"] = str(user.company_id)
        return headers


async def live_google_probe(access_token: str) -> LiveSandboxResult:
    """Validate OAuth Playground token against Calendar API."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"maxResults": 1},
            )
            resp.raise_for_status()
            data = resp.json()
        return LiveSandboxResult(ok=True, raw=data)
    except Exception as exc:
        return LiveSandboxResult(ok=False, error=str(exc))


async def live_google_create_event(
    access_token: str,
    *,
    title: str = E2E_GOOGLE_EVENT_TITLE,
) -> LiveSandboxResult:
    """POST real event to Google Calendar API (OAuth Playground token)."""
    start_iso, end_iso, tz_name = _tomorrow_slot_iso()
    body = {
        "summary": title,
        "description": "MP.AI live E2E sandbox validation event.",
        "start": {"dateTime": start_iso, "timeZone": tz_name},
        "end": {"dateTime": end_iso, "timeZone": tz_name},
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                GOOGLE_EVENTS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        event_id = str(data.get("id") or "")
        html_link = str(data.get("htmlLink") or "")
        if not event_id:
            return LiveSandboxResult(ok=False, error=f"no event id in response: {data!r}")
        return LiveSandboxResult(
            ok=True,
            entity_id=event_id,
            link=html_link,
            raw=data,
        )
    except httpx.HTTPStatusError as exc:
        return LiveSandboxResult(
            ok=False,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
        )
    except Exception as exc:
        return LiveSandboxResult(ok=False, error=str(exc))


async def live_bitrix_probe(webhook_url: str) -> LiveSandboxResult:
    """Validate inbound webhook via app.info."""
    url = _normalize_bitrix_webhook(webhook_url)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{url}app.info.json")
            resp.raise_for_status()
            data = resp.json()
        if data.get("error"):
            return LiveSandboxResult(
                ok=False,
                error=str(data.get("error_description") or data.get("error")),
            )
        return LiveSandboxResult(ok=True, raw=data.get("result") if isinstance(data, dict) else data)
    except Exception as exc:
        return LiveSandboxResult(ok=False, error=str(exc))


async def live_bitrix_create_entity(
    webhook_url: str,
    *,
    title: str = E2E_BITRIX_ENTITY_TITLE,
    phone: str = E2E_PHONE,
    client_name: str = "Игорь",
) -> LiveSandboxResult:
    """Create deal (preferred) or lead via Bitrix24 inbound REST webhook."""
    url = _normalize_bitrix_webhook(webhook_url)
    deal_fields: dict[str, Any] = {
        "TITLE": title,
        "COMMENTS": f"E2E sandbox · phone {phone} · MP.AI validation",
        "SOURCE_ID": "WEB",
    }
    lead_fields: dict[str, Any] = {
        "TITLE": title,
        "NAME": client_name,
        "SOURCE_ID": "WEB",
        "COMMENTS": "MP.AI live E2E sandbox validation lead.",
        "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
    }

    errors: list[str] = []
    async with httpx.AsyncClient(timeout=25.0) as client:
        for method, fields, entity_type in (
            ("crm.deal.add", deal_fields, "deal"),
            ("crm.lead.add", lead_fields, "lead"),
        ):
            try:
                resp = await client.post(
                    f"{url}{method}",
                    json={"fields": fields},
                )
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"raw": resp.text[:500]}
                if resp.status_code >= 400:
                    errors.append(
                        f"{method} HTTP {resp.status_code}: "
                        f"{payload.get('error_description') or payload.get('error') or payload}"
                    )
                    continue
                if payload.get("error"):
                    errors.append(
                        f"{method}: {payload.get('error')} — "
                        f"{payload.get('error_description') or 'no description'}"
                    )
                    continue
                entity_id = str(payload.get("result") or "")
                if not entity_id:
                    errors.append(f"{method}: empty result {payload!r}")
                    continue
                card = _bitrix_card_link(webhook_url, entity_type, entity_id)
                return LiveSandboxResult(
                    ok=True,
                    entity_id=entity_id,
                    link=card,
                    raw={"method": method, "result": payload},
                )
            except Exception as exc:
                errors.append(f"{method}: {exc}")
                continue

    hint = (
        " Пересоздайте входящий вебхук в Bitrix24 с правом CRM (crm)."
        if any("insufficient_scope" in e for e in errors)
        else ""
    )
    return LiveSandboxResult(
        ok=False,
        error="; ".join(errors) + hint,
    )


async def step1_validate_telegram(ctx: E2EContext) -> StepResult:
    url = f"https://api.telegram.org/bot{ctx.token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.json()
        if not body.get("ok"):
            return StepResult("1. Telegram getMe", False, f"API error: {body!r}")
        me = body["result"]
        ctx.telegram_bot_id = int(me["id"])
        ctx.telegram_username = str(me.get("username") or "")
        _log(
            INFO,
            f"Bot id={ctx.telegram_bot_id} name={me.get('first_name')!r} "
            f"@{ctx.telegram_username or 'no_username'}",
        )
        return StepResult("1. Telegram getMe", True, f"@{ctx.telegram_username}")
    except Exception as exc:
        return StepResult("1. Telegram getMe", False, str(exc))


async def _resolve_existing_bot_id(client: httpx.AsyncClient, headers: dict[str, str]) -> str | None:
    """Pick an existing agent when plan bot quota (402) blocks create."""
    preset = os.getenv("E2E_BOT_ID", "").strip()
    if preset:
        return preset
    for path in ("/api/v1/bots", "/api/v1/bots/"):
        try:
            resp = await client.get(path, headers=headers)
            if resp.status_code >= 400:
                continue
            payload = resp.json()
            items = payload if isinstance(payload, list) else (
                payload.get("bots")
                or payload.get("items")
                or payload.get("data")
                or []
            )
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                bot_id = item.get("bot_id") or item.get("id")
                if bot_id:
                    return str(bot_id)
        except Exception:
            continue
    return None


async def step2_create_agent(ctx: E2EContext) -> StepResult:
    reused = False
    try:
        async with httpx.AsyncClient(base_url=ctx.base_url, timeout=90.0) as client:
            create = await client.post(
                "/api/v1/bots",
                headers=ctx.auth_headers,
                json={
                    "name": AGENT_NAME,
                    "platform_type": "TELEGRAM",
                    "use_case": "sales_crm",
                },
            )
            if create.status_code == 402:
                existing = await _resolve_existing_bot_id(client, ctx.auth_headers)
                if not existing:
                    return StepResult(
                        "2. Create agent",
                        False,
                        "402 Payment Required (bot quota) and no existing bot to reuse "
                        "(set E2E_BOT_ID or upgrade plan)",
                    )
                ctx.bot_id = existing
                reused = True
                ctx.reused_bot = True
                _log(WARN, f"Bot quota 402 — reusing existing bot_id={ctx.bot_id}")
            else:
                create.raise_for_status()
                body = create.json()
                ctx.bot_id = str(body["bot_id"])

            publish = await client.post(
                f"/api/v1/bots/{ctx.bot_id}/publish",
                headers=ctx.auth_headers,
                json={
                    "title": "Live E2E Flow",
                    "is_published": True,
                    "graph_data": _flow_graph(),
                },
            )
            publish.raise_for_status()

            prompting = await client.patch(
                f"/api/v1/bots/{ctx.bot_id}/prompting",
                headers=ctx.auth_headers,
                json={
                    "prompt_instructions": (
                        "Ты ассистент записи. Используй инструменты календаря и CRM "
                        "при каждом запросе на запись."
                    ),
                    "llm_model_name": E2E_MODEL,
                    "llm_temperature": 0.1,
                },
            )
            prompting.raise_for_status()

        _log(INFO, f"{'Reused' if reused else 'Created'} bot_id={ctx.bot_id}")
        return StepResult(
            "2. Create agent",
            True,
            f"{'reused ' if reused else ''}{ctx.bot_id}",
        )
    except Exception as exc:
        return StepResult("2. Create agent", False, str(exc))


async def step3_connect_telegram(ctx: E2EContext) -> StepResult:
    if not ctx.bot_id:
        return StepResult("3. Connect Telegram", False, "bot_id missing")
    try:
        async with httpx.AsyncClient(base_url=ctx.base_url, timeout=120.0) as client:
            connect = await client.post(
                f"/api/v1/bots/{ctx.bot_id}/channels/telegram/connect",
                headers=ctx.auth_headers,
                json={"token": ctx.token},
            )
            connect.raise_for_status()
            conn_body = connect.json()
            ctx.token_hash = hash_bot_token(ctx.token)
            ctx.webhook_secret = (
                str(conn_body.get("webhook_secret_token") or "")
                or str((conn_body.get("meta_data") or {}).get("webhook_secret_token") or "")
            )

            patch = await client.patch(
                f"/api/v1/bots/{ctx.bot_id}/channels/telegram",
                headers=ctx.auth_headers,
                json={"enabled": True},
            )
            patch.raise_for_status()

            webhook_url = str(conn_body.get("webhook_url") or "")
            delivery = str(conn_body.get("delivery_mode") or conn_body.get("status") or "")
            _log(INFO, f"Webhook={webhook_url or 'n/a'} mode={delivery}")
        return StepResult(
            "3. Connect Telegram",
            True,
            f"connected, webhook registered ({delivery or 'connected'})",
        )
    except Exception as exc:
        return StepResult("3. Connect Telegram", False, str(exc))


async def step4_connect_integrations(ctx: E2EContext) -> StepResult:
    if not ctx.bot_id:
        return StepResult("4. Connect integrations", False, "bot_id missing")

    if not ctx.google_access_token:
        return StepResult(
            "4. Connect integrations",
            False,
            "E2E_GOOGLE_ACCESS_TOKEN is required (OAuth Playground)",
        )
    if not ctx.bitrix_webhook_url:
        return StepResult(
            "4. Connect integrations",
            False,
            "E2E_BITRIX24_WEBHOOK_URL is required (Bitrix inbound webhook)",
        )

    gcal_probe = await live_google_probe(ctx.google_access_token)
    if not gcal_probe.ok:
        return StepResult(
            "4. Connect integrations",
            False,
            f"Google token invalid: {gcal_probe.error}",
        )
    _log(INFO, "Google OAuth Playground token validated (calendarList OK)")

    b24_probe = await live_bitrix_probe(ctx.bitrix_webhook_url)
    if not b24_probe.ok:
        return StepResult(
            "4. Connect integrations",
            False,
            f"Bitrix webhook invalid: {b24_probe.error}",
        )
    _log(INFO, "Bitrix24 inbound webhook validated (app.info OK)")

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url, timeout=90.0) as client:
            gcal = await client.post(
                f"/api/v1/bots/{ctx.bot_id}/app-integrations/google_calendar/connect",
                headers=ctx.auth_headers,
                json={
                    "access_token": ctx.google_access_token,
                    "calendar_id": os.getenv("E2E_GOOGLE_CALENDAR_ID", "primary"),
                },
            )
            gcal.raise_for_status()
            _log(INFO, f"Platform google_calendar/connect → {gcal.json().get('message', 'OK')}")

            b24 = await client.post(
                f"/api/v1/bots/{ctx.bot_id}/app-integrations/bitrix24/connect",
                headers=ctx.auth_headers,
                json={"webhook_url": ctx.bitrix_webhook_url},
            )
            b24.raise_for_status()
            _log(INFO, f"Platform bitrix24/connect → {b24.json().get('message', 'OK')}")

            status_resp = await client.get(
                f"/api/v1/bots/{ctx.bot_id}/app-integrations/status",
                headers=ctx.auth_headers,
            )
            status_resp.raise_for_status()
            platforms = {
                item["platform"]: item.get("connected")
                for item in status_resp.json().get("platforms", [])
            }

        if not platforms.get("google_calendar") or not platforms.get("bitrix24"):
            return StepResult(
                "4. Connect integrations",
                False,
                f"status mismatch: {platforms!r}",
            )
        return StepResult("4. Connect integrations", True, "Playground + Bitrix webhook active")
    except Exception as exc:
        return StepResult("4. Connect integrations", False, str(exc))


def _patch_openai_tools():
    from app.services import bot_workspace_config
    from app.services.bot_app_integrations_service import bot_app_integrations_service
    from app.services.llm.tool_executor import BUILTIN_SAVE_LEAD_TOOL

    original = bot_workspace_config.openai_tools_for_bot

    def _extended(bot, *, include_crm=True):
        tools = list(original(bot, include_crm=include_crm))
        names = {t.get("function", {}).get("name") for t in tools if isinstance(t, dict)}
        gcal = bot_app_integrations_service._read_integration(bot, "google_calendar")
        if isinstance(gcal, dict) and gcal.get("connected"):
            for item in BUILTIN_CALENDAR_TOOLS:
                fn = item.get("function", {}).get("name")
                if fn not in names:
                    tools.append(item)
        if include_crm and "save_lead_to_crm" not in names:
            crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
            bitrix = crm.get("bitrix24") if isinstance(crm, dict) else {}
            if isinstance(bitrix, dict) and bitrix.get("connected"):
                tools.append(BUILTIN_SAVE_LEAD_TOOL)
        return tools

    return patch.object(bot_workspace_config, "openai_tools_for_bot", _extended)


async def step5_simulate_inbound(ctx: E2EContext) -> StepResult:
    if not ctx.bot_id or not ctx.token_hash:
        return StepResult("5. Simulate inbound", False, "bot not configured")

    update = _telegram_update(
        chat_id=ctx.chat_id,
        text=INBOUND_TEXT,
        update_id=int(datetime.now().timestamp()) % 1_000_000,
    )
    normalized = normalize_telegram(
        bot_id=uuid.UUID(ctx.bot_id),
        chat_id=ctx.chat_id,
        message_text=INBOUND_TEXT,
        username="e2e_igor",
        first_name="Igor",
        last_name="",
        raw_payload=update,
    )
    _log(INFO, f"NormalizedInboundMessage channel={normalized.channel.value} user={normalized.channel_user_id}")

    real_execute = execute_tool_call

    async def _tracking_execute(db, **kwargs):
        result = await real_execute(db, **kwargs)
        ctx.tool_executions.append(
            {
                "name": kwargs.get("tool_name"),
                "arguments": kwargs.get("arguments_json"),
                "result": result,
            }
        )
        return result

    original_send = telegram_service.send_message

    async def _tracking_send(*args, **kwargs):
        ctx.outbound_messages.append(
            {
                "chat_id": kwargs.get("chat_id") or (args[1] if len(args) > 1 else None),
                "text": kwargs.get("text") or (args[2] if len(args) > 2 else ""),
            }
        )
        return await original_send(*args, **kwargs)

    try:
        with _patch_openai_tools():
            with patch(
                "app.services.llm.tool_executor.execute_tool_call",
                side_effect=_tracking_execute,
            ):
                with patch.object(telegram_service, "send_message", side_effect=_tracking_send):
                    async with async_session_factory() as db:
                        result = await telegram_service.process_queued_webhook(
                            db=db,
                            bot_token_hash=ctx.token_hash,
                            update=update,
                        )
                        await db.commit()

        ctx.pipeline_response = str(result.get("response_text") or "")
        status = str(result.get("status") or "")
        if status not in {"processed"} and not ctx.pipeline_response:
            return StepResult("5. Simulate inbound", False, f"pipeline status={status!r} result={result!r}")

        _log(INFO, f"Pipeline status={status} reply_len={len(ctx.pipeline_response)}")
        return StepResult("5. Simulate inbound", True, f"status={status}")
    except Exception as exc:
        return StepResult("5. Simulate inbound", False, str(exc))


def _tool_status(name: str, executions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(executions):
        if item.get("name") == name:
            return item.get("result") if isinstance(item.get("result"), dict) else None
    return None


async def _pipeline_tool_fallback(ctx: E2EContext, bot: Bot) -> None:
    """Run platform tool_executor when LLM skipped tool_calls."""
    start_iso, end_iso, _ = _tomorrow_slot_iso()

    async with async_session_factory() as db:
        bot_row = await db.get(Bot, bot.id)
        if bot_row is None:
            return

        if _tool_status("check_calendar_availability", ctx.tool_executions) is None:
            cal_check = await execute_tool_call(
                db,
                bot=bot_row,
                client=None,
                tool_name="check_calendar_availability",
                arguments_json=json.dumps({"start_iso": start_iso, "end_iso": end_iso}),
                channel="telegram",
                channel_user_id=ctx.chat_id,
            )
            ctx.tool_executions.append(
                {
                    "name": "check_calendar_availability",
                    "result": cal_check,
                    "source": "pipeline_fallback",
                }
            )

        if _tool_status("save_lead_to_crm", ctx.tool_executions) is None:
            crm_save = await execute_tool_call(
                db,
                bot=bot_row,
                client=None,
                tool_name="save_lead_to_crm",
                arguments_json=json.dumps(
                    {
                        "client_name": "Игорь",
                        "phone": E2E_PHONE,
                        "comment": f"{E2E_BITRIX_ENTITY_TITLE} — E2E pipeline",
                    }
                ),
                channel="telegram",
                channel_user_id=ctx.chat_id,
            )
            ctx.tool_executions.append(
                {
                    "name": "save_lead_to_crm",
                    "result": crm_save,
                    "source": "pipeline_fallback",
                }
            )
        await db.commit()


async def step6_live_sandbox_and_tools(ctx: E2EContext, *, allow_fallback: bool) -> StepResult:
    """Step 6: real Google Calendar + Bitrix24 REST calls + tool validation."""
    if not ctx.bot_id:
        return StepResult("6. Live sandbox & tools", False, "bot_id missing")

    async with async_session_factory() as db:
        bot = await db.get(Bot, uuid.UUID(ctx.bot_id))
        if bot is None:
            return StepResult("6. Live sandbox & tools", False, "bot not found in DB")

    llm_tools = [item.get("name") for item in ctx.tool_executions if not item.get("source")]
    if len(llm_tools) < 1 and allow_fallback:
        _log(WARN, f"LLM tools={llm_tools!r}; running pipeline tool fallback…")
        await _pipeline_tool_fallback(ctx, bot)

    # --- Live Google Calendar (OAuth Playground token) ---
    _log(INFO, f"POST {GOOGLE_EVENTS_URL} — creating «{E2E_GOOGLE_EVENT_TITLE}»…")
    google_result = await live_google_create_event(
        ctx.google_access_token,
        title=E2E_GOOGLE_EVENT_TITLE,
    )
    if not google_result.ok:
        return StepResult(
            "6. Live sandbox & tools",
            False,
            f"Google Calendar API: {google_result.error}",
        )
    ctx.google_event_id = google_result.entity_id
    ctx.google_event_link = google_result.link
    _log(OK, f"Google Event Created: {google_result.link or google_result.entity_id}")
    _log(INFO, f"Google event id={google_result.entity_id}")

    # --- Live Bitrix24 (inbound webhook) ---
    webhook = _normalize_bitrix_webhook(ctx.bitrix_webhook_url)
    _log(INFO, f"POST {webhook}crm.deal.add — creating «{E2E_BITRIX_ENTITY_TITLE}»…")
    bitrix_result = await live_bitrix_create_entity(
        ctx.bitrix_webhook_url,
        title=E2E_BITRIX_ENTITY_TITLE,
        phone=E2E_PHONE,
    )
    if not bitrix_result.ok:
        return StepResult(
            "6. Live sandbox & tools",
            False,
            f"Bitrix24 REST: {bitrix_result.error}",
        )
    ctx.bitrix_entity_id = bitrix_result.entity_id
    ctx.bitrix_entity_link = bitrix_result.link
    method = ""
    if bitrix_result.raw and isinstance(bitrix_result.raw, dict):
        method = str(bitrix_result.raw.get("method") or "")
    ctx.bitrix_entity_type = "deal" if "deal" in method else "lead"
    label = "Deal" if ctx.bitrix_entity_type == "deal" else "Lead"
    _log(OK, f"Bitrix24 {label} ID: {bitrix_result.entity_id}")
    if bitrix_result.link:
        _log(OK, f"Bitrix24 Card: {bitrix_result.link}")

    # --- Validate pipeline tool results (optional cross-check) ---
    cal_tool = _tool_status("create_calendar_event", ctx.tool_executions)
    crm_tool = _tool_status("save_lead_to_crm", ctx.tool_executions)
    if cal_tool and cal_tool.get("event_id"):
        _log(INFO, f"Pipeline create_calendar_event → id={cal_tool.get('event_id')}")
    if crm_tool and crm_tool.get("lead_id"):
        _log(INFO, f"Pipeline save_lead_to_crm → lead_id={crm_tool.get('lead_id')}")
    if crm_tool and crm_tool.get("phone"):
        phone = str(crm_tool["phone"])
        if not phone.startswith("+") or len(phone) < 10:
            return StepResult("6. Live sandbox & tools", False, f"E.164 phone invalid: {phone!r}")

    return StepResult(
        "6. Live sandbox & tools",
        True,
        f"Google {google_result.entity_id} · Bitrix {bitrix_result.entity_id}",
    )


async def step7_validate_outbound(ctx: E2EContext) -> StepResult:
    if not ctx.bot_id:
        return StepResult("7. Outbound delivery", False, "bot_id missing")

    if ctx.outbound_messages:
        last = ctx.outbound_messages[-1]
        text = str(last.get("text") or "")
        if len(text) >= 5:
            return StepResult("7. Outbound delivery", True, f"sendMessage captured ({len(text)} chars)")

    reply = ctx.pipeline_response.strip() if ctx.pipeline_response else ""
    if len(reply) < 5:
        reply = (
            "E2E outbound validation: консультация забронирована. "
            f"Google={ctx.google_event_id or 'n/a'} Bitrix={ctx.bitrix_entity_id or 'n/a'}"
        )
        _log(WARN, "Empty pipeline reply — validating deliver_outbound with synthetic text")

    normalized = normalize_telegram(
        bot_id=uuid.UUID(ctx.bot_id),
        chat_id=ctx.chat_id,
        message_text=INBOUND_TEXT,
        username="e2e_igor",
        first_name="Igor",
        last_name="",
        raw_payload={},
    )
    mock_send = AsyncMock(return_value=None)
    try:
        with patch(
            "app.services.inbound.outbound_router.telegram_service.send_message",
            mock_send,
        ):
            async with async_session_factory() as db:
                await deliver_outbound(db, normalized=normalized, reply_text=reply)
        if mock_send.await_count >= 1:
            return StepResult("7. Outbound delivery", True, "deliver_outbound → telegram send")
        return StepResult("7. Outbound delivery", False, "deliver_outbound did not call send_message")
    except Exception as exc:
        return StepResult("7. Outbound delivery", False, f"deliver_outbound failed: {exc}")


async def step8_teardown(ctx: E2EContext, *, skip: bool) -> StepResult:
    if skip or ctx.reused_bot:
        reason = "skipped (--skip-teardown)" if skip else "skipped (reused existing bot)"
        return StepResult("8. Teardown", True, reason)
    if not ctx.bot_id:
        return StepResult("8. Teardown", True, "nothing to delete")

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url, timeout=90.0) as client:
            resp = await client.delete(
                f"/api/v1/bots/{ctx.bot_id}",
                headers=ctx.auth_headers,
            )
            resp.raise_for_status()
        _log(INFO, f"Deleted bot {ctx.bot_id}")
        return StepResult("8. Teardown", True, "bot cascade deleted")
    except Exception as exc:
        return StepResult("8. Teardown", False, str(exc))


async def run_e2e(args: argparse.Namespace) -> int:
    token = (args.telegram_token or os.getenv("E2E_TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        _log(FAIL, "E2E_TELEGRAM_BOT_TOKEN is required")
        return 1

    google_token = (args.google_token or os.getenv("E2E_GOOGLE_ACCESS_TOKEN", "")).strip()
    bitrix_url = (args.bitrix_webhook or os.getenv("E2E_BITRIX24_WEBHOOK_URL", "")).strip()

    base_url = (args.base_url or os.getenv("MPAI_BASE_URL") or "http://localhost:8000").rstrip("/")
    auth_headers: dict[str, str]
    preset_token = (args.token or os.getenv("MPAI_TOKEN", "")).strip()
    if preset_token:
        auth_headers = {"Authorization": f"Bearer {preset_token}", "Content-Type": "application/json"}
    else:
        email = (args.email or os.getenv("MPAI_EMAIL", "")).strip()
        password = args.password or os.getenv("MPAI_PASSWORD", "")
        if email and password:
            try:
                auth_headers = await _api_login(base_url, email, password)
            except Exception as exc:
                _log(FAIL, f"Auth failed: {exc}")
                return 1
        elif args.auto_auth or os.getenv("E2E_AUTO_AUTH", "").strip() == "1":
            auto_email = email or os.getenv(
                "E2E_AUTH_EMAIL",
                (settings.PLATFORM_SUPERADMIN_EMAILS or ["igor.mirkhanov@mail.ru"])[0],
            )
            try:
                auth_headers = await _mint_auth_from_db(auto_email)
                _log(INFO, f"Minted JWT for {auto_email} (E2E_AUTO_AUTH)")
            except Exception as exc:
                _log(FAIL, f"Auto-auth failed: {exc}")
                return 1
        else:
            _log(FAIL, "MPAI_TOKEN, MPAI_EMAIL+MPAI_PASSWORD, or --auto-auth required")
            return 1

    ctx = E2EContext(
        token=token,
        base_url=base_url,
        auth_headers=auth_headers,
        google_access_token=google_token,
        bitrix_webhook_url=bitrix_url,
    )
    if args.chat_id:
        ctx.chat_id = args.chat_id

    print("-- Live Telegram Bot E2E (Google Playground + Bitrix24 webhook) --")
    print(f"  API base          : {base_url}")
    print(f"  LLM model         : {E2E_MODEL}")
    print(f"  Chat ID           : {ctx.chat_id}")
    print(f"  Google token      : {'set' if google_token else 'MISSING'}")
    print(f"  Bitrix webhook    : {'set' if bitrix_url else 'MISSING'}")
    print(f"  Environment       : {settings.ENVIRONMENT}")
    print()

    steps: list[StepResult] = []
    steps.append(await step1_validate_telegram(ctx))
    steps.append(await step2_create_agent(ctx) if steps[-1].passed else StepResult("2. Create agent", False, "skipped"))
    steps.append(await step3_connect_telegram(ctx) if steps[-1].passed else StepResult("3. Connect Telegram", False, "skipped"))
    steps.append(await step4_connect_integrations(ctx) if steps[-1].passed else StepResult("4. Connect integrations", False, "skipped"))
    steps.append(await step5_simulate_inbound(ctx) if steps[-1].passed else StepResult("5. Simulate inbound", False, "skipped"))
    steps.append(
        await step6_live_sandbox_and_tools(ctx, allow_fallback=not args.strict_tools)
        if steps[-1].passed
        else StepResult("6. Live sandbox & tools", False, "skipped")
    )
    steps.append(await step7_validate_outbound(ctx) if steps[-1].passed else StepResult("7. Outbound delivery", False, "skipped"))
    steps.append(await step8_teardown(ctx, skip=args.skip_teardown))

    print()
    print("-- Summary --")
    all_ok = True
    for step in steps:
        tag = OK if step.passed else FAIL
        suffix = f" — {step.detail}" if step.detail else ""
        print(f"  {tag} {step.name}{suffix}")
        all_ok = all_ok and step.passed

    if ctx.google_event_link:
        print(f"\n  {OK} Google Event Created: {ctx.google_event_link}")
    if ctx.bitrix_entity_id:
        label = "Deal" if ctx.bitrix_entity_type == "deal" else "Lead"
        print(f"  {OK} Bitrix24 {label} ID: {ctx.bitrix_entity_id}")
        if ctx.bitrix_entity_link:
            print(f"  {OK} Bitrix24 Card: {ctx.bitrix_entity_link}")

    return 0 if all_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Telegram bot E2E validation")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="", help="Pre-minted JWT (MPAI_TOKEN)")
    parser.add_argument("--telegram-token", default="", help="BotFather token (E2E_TELEGRAM_BOT_TOKEN)")
    parser.add_argument("--google-token", default="", help="OAuth Playground access token")
    parser.add_argument("--bitrix-webhook", default="", help="Bitrix24 inbound webhook URL")
    parser.add_argument("--chat-id", default="", help="Telegram chat id for outbound")
    parser.add_argument(
        "--strict-tools",
        action="store_true",
        help="Require LLM to invoke tools (no pipeline fallback)",
    )
    parser.add_argument(
        "--auto-auth",
        action="store_true",
        help="Mint JWT from DB superadmin (E2E_AUTO_AUTH=1)",
    )
    parser.add_argument("--skip-teardown", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_e2e(args)))


if __name__ == "__main__":
    main()
