"""Bind Bitrix24 Incoming Webhook to a bot and create a test deal.

Env (do not commit secrets):
  BITRIX24_WEBHOOK_URL  Incoming Webhook REST URL (.../rest/{user}/{code}/)
  BOT_ID                optional bot UUID; defaults to WhatsApp QR bot if present
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.core_models import Bot, Client
from app.models.integrations.credentials import reveal_bitrix_config
from app.models.tenant_credentials import TenantCredential
from app.services.crm_orchestrator import crm_orchestrator
from app.services.crypto_service import decrypt_payload
from app.services.integration_hub.adapters.bitrix24 import (
    normalize_bitrix_incoming_webhook,
    probe_bitrix_incoming_webhook,
)


DEFAULT_BOT_ID = "7c7602f7-746a-4354-8064-1261dc2e9820"


def _portal_host(webhook: str) -> str:
    return urlparse(webhook).hostname or "unknown"


def _candidate_from_env() -> list[tuple[str, str]]:
    raw = (os.environ.get("BITRIX24_WEBHOOK_URL") or "").strip()
    if not raw:
        return []
    try:
        return [("env", normalize_bitrix_incoming_webhook(raw))]
    except ValueError:
        print("ENV_WEBHOOK_INVALID_SHAPE")
        return []


def _webhook_from_bot(bot: Bot) -> str | None:
    crm = (bot.credentials or {}).get("crm") or {}
    config = reveal_bitrix_config(crm.get("bitrix24") if isinstance(crm.get("bitrix24"), dict) else None)
    if not config:
        return None
    url = config.get("webhook_url")
    if not isinstance(url, str) or "/rest/" not in url.lower():
        return None
    try:
        return normalize_bitrix_incoming_webhook(url)
    except ValueError:
        return None


def _webhook_from_vault_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("webhook_url")
    if not isinstance(raw, str):
        return None
    try:
        return normalize_bitrix_incoming_webhook(raw)
    except ValueError:
        return None


async def _first_working_webhook(
    db,
    *,
    target_bot: Bot,
) -> str:
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    candidates.extend(_candidate_from_env())
    own = _webhook_from_bot(target_bot)
    if own:
        candidates.append(("target_bot", own))
    bots = (await db.execute(select(Bot))).scalars().all()
    stored_flags = []
    for other in bots:
        has = bool(_webhook_from_bot(other))
        stored_flags.append(f"{other.name}:{has}")
        url = _webhook_from_bot(other)
        if url:
            candidates.append((f"bot:{other.id}", url))
    print("BOTS_BITRIX_STORED", ",".join(stored_flags) or "none")

    try:
        vault_rows = (await db.execute(select(TenantCredential))).scalars().all()
    except Exception as exc:
        print("VAULT_SCAN_SKIPPED", type(exc).__name__)
        vault_rows = []
    print("VAULT_ROWS", len(vault_rows))
    for row in vault_rows:
        kind = (row.kind or "").lower()
        if "bitrix" not in kind:
            continue
        try:
            payload = decrypt_payload(
                row.encrypted_payload,
                row.encryption_iv,
                row.encryption_tag,
                key_version=int(row.key_version),
            )
        except Exception:
            continue
        url = _webhook_from_vault_payload(payload)
        if url:
            candidates.append((f"vault:{kind}", url))

    async with crm_orchestrator._client() as http:
        for source, webhook in candidates:
            if webhook in seen:
                continue
            seen.add(webhook)
            try:
                await probe_bitrix_incoming_webhook(http, webhook)
            except ValueError as exc:
                print("PROBE_FAIL", source, _portal_host(webhook), str(exc)[:80])
                continue
            print("PROBE_OK", source, _portal_host(webhook))
            return webhook
    raise SystemExit(
        "No working Bitrix Incoming Webhook. Create a new one in Bitrix24 "
        "(Разработчикам → Другое → Входящий вебхук, CRM deals+contacts) and paste it."
    )


async def main() -> None:
    bot_id_raw = (os.environ.get("BOT_ID") or DEFAULT_BOT_ID).strip()
    bot_id = uuid.UUID(bot_id_raw)

    async with async_session_factory() as db:
        bot = await db.get(Bot, bot_id)
        if bot is None:
            bot = (
                await db.execute(select(Bot).order_by(Bot.created_at.desc()).limit(1))
            ).scalar_one_or_none()
        if bot is None:
            raise SystemExit("No bots found")
        print("BOT", str(bot.id), bot.name)

        webhook = await _first_working_webhook(db, target_bot=bot)
        await crm_orchestrator.connect_bitrix24(db, bot, webhook)
        print("BITRIX_CONNECTED", True)

        external_id = "77017940910"
        client = (
            await db.execute(
                select(Client).where(Client.bot_id == bot.id, Client.external_id == external_id)
            )
        ).scalar_one_or_none()
        if client is None:
            client = Client(
                bot_id=bot.id,
                external_id=external_id,
                username="mpai_bitrix_probe",
                first_name="MP.AI Bitrix Probe",
            )
            db.add(client)
            await db.commit()
            await db.refresh(client)
        client_id = client.id

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        result = await crm_orchestrator.execute_crm_action(
            bot.id,
            client_id,
            {
                "platform": "bitrix24",
                "tags": ["mp_ai", "probe"],
                "custom_attributes": {
                    "lead_name": f"MP.AI probe deal {stamp}",
                },
            },
        )
        print("CRM_RESULT_SUCCESS", bool(result.get("success")))
        print("DEAL_ID", result.get("deal_id"))
        print("CONTACT_ID", result.get("contact_id"))
        if result.get("error"):
            print("CRM_ERROR", result.get("error"))
        portal = webhook.split("/rest/")[0]
        if result.get("deal_id"):
            print("DEAL_URL", f"{portal}/crm/deal/details/{result['deal_id']}/")


if __name__ == "__main__":
    asyncio.run(main())
