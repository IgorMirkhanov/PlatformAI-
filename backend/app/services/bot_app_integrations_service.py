"""Bot app integrations catalog (CRM + Calendar + Kaspi + Jivo + U-ON).

Credentials live under ``bot.credentials["integrations"][platform]`` with
sensitive fields AES-sealed. AmoCRM/Bitrix24 remain in ``credentials["crm"]``
for backward compatibility and are mirrored into status responses.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import resolve_webhook_base_url, settings
from app.core.security import decrypt_credential, encrypt_credential, generate_webhook_secret
from app.models.core_models import Bot
from app.models.integrations import (
    get_amocrm_access_token,
    get_bitrix_webhook_url,
    reveal_amocrm_config,
    reveal_bitrix_config,
)

# Catalog platforms shown on the Integrations tab (screenshot parity).
INTEGRATION_PLATFORMS: tuple[str, ...] = (
    "amocrm",
    "kommo",
    "bitrix24",
    "google_calendar",
    "kaspi_receipts",
    "kaspi_pay",
    "custom_webhook",
    "jivo",
    "uon",
)

_SENSITIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "google_calendar": ("refresh_token", "access_token", "client_secret"),
    "kaspi_receipts": ("api_key",),
    "kaspi_pay": ("merchant_token", "api_key", "secret_key"),
    "custom_webhook": ("hmac_secret", "webhook_secret"),
    "jivo": ("token", "api_key", "webhook_secret"),
    "uon": ("api_key", "password"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seal_block(platform: str, config: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(config)
    for field in _SENSITIVE_FIELDS.get(platform, ()):
        value = sealed.get(field)
        if isinstance(value, str) and value and not value.startswith(("aesgcm:", "enc:", "plain:")):
            sealed[field] = encrypt_credential(value)
    return sealed


def _reveal_block(platform: str, config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    revealed = dict(config)
    for field in _SENSITIVE_FIELDS.get(platform, ()):
        value = revealed.get(field)
        if isinstance(value, str) and value:
            try:
                revealed[field] = decrypt_credential(value)
            except Exception:
                pass
    return revealed


class BotAppIntegrationsService:
    """Connect / disconnect / status / runtime helpers for Integrations tab."""

    async def get_status(self, db: AsyncSession, bot_id: uuid.UUID) -> dict[str, Any]:
        bot = await self._require_bot(db, bot_id)
        platforms: list[dict[str, Any]] = []
        for platform in INTEGRATION_PLATFORMS:
            platforms.append(self._status_for(bot, platform))
        return {"bot_id": str(bot_id), "platforms": platforms}

    async def connect(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        platform: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        platform = platform.strip().lower()
        if platform not in INTEGRATION_PLATFORMS:
            raise ValueError(f"Unsupported integration: {platform}")

        bot = await self._require_bot(db, bot_id)

        if platform == "amocrm":
            return await self._connect_amocrm(db, bot, payload)
        if platform == "kommo":
            payload = dict(payload)
            payload.setdefault("base_domain", "company.kommo.com")
            return await self._connect_amocrm(db, bot, payload, storage_platform="kommo")
        if platform == "bitrix24":
            return await self._connect_bitrix(db, bot, payload)
        if platform == "google_calendar":
            return await self._connect_google_calendar(db, bot, payload)
        if platform == "kaspi_receipts":
            return await self._connect_kaspi_receipts(db, bot, payload)
        if platform == "kaspi_pay":
            return await self._connect_kaspi_pay(db, bot, payload)
        if platform == "custom_webhook":
            return await self._connect_custom_webhook(db, bot, payload)
        if platform == "jivo":
            return await self._connect_jivo(db, bot, payload)
        if platform == "uon":
            return await self._connect_uon(db, bot, payload)
        raise ValueError(f"Unsupported integration: {platform}")

    async def disconnect(self, db: AsyncSession, bot_id: uuid.UUID, platform: str) -> dict[str, Any]:
        platform = platform.strip().lower()
        bot = await self._require_bot(db, bot_id)
        if platform in {"amocrm", "bitrix24", "kommo"}:
            if platform == "kommo":
                self._write_integration(bot, "kommo", {})
            else:
                credentials = dict(bot.credentials or {})
                crm = dict(credentials.get("crm") or {})
                crm.pop(platform, None)
                credentials["crm"] = crm
                bot.credentials = credentials
        else:
            self._write_integration(bot, platform, {})
        await db.flush()
        return {
            "bot_id": str(bot_id),
            "platform": platform,
            "connected": False,
            "message": f"{platform} отключён.",
        }

    async def patch(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        platform: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Toggle sync / update mapping without full reconnect."""
        platform = platform.strip().lower()
        bot = await self._require_bot(db, bot_id)

        if platform in {"amocrm", "bitrix24"}:
            from app.services.crm_integration_service import crm_integration_service
            from app.schemas.crm_schemas import CRMIntegrationPatchRequest

            result = await crm_integration_service.patch_integration(
                db,
                bot_id,
                platform,
                CRMIntegrationPatchRequest(**{
                    k: v for k, v in payload.items() if v is not None
                }),
            )
            return {
                "bot_id": str(bot_id),
                "platform": platform,
                "connected": result.connected,
                "sync_enabled": result.sync_enabled,
                "message": result.message,
            }

        current = self._read_integration(bot, platform)
        if not current.get("connected"):
            raise ValueError("Integration is not connected.")
        for key in ("sync_enabled", "calendar_id", "pipeline_id", "default_tags", "meta"):
            if key in payload and payload[key] is not None:
                current[key] = payload[key]
        current["updated_at"] = _now_iso()
        self._write_integration(bot, platform, current)
        await db.flush()
        return {
            "bot_id": str(bot_id),
            "platform": platform,
            "connected": True,
            "sync_enabled": bool(current.get("sync_enabled", True)),
            "message": "Настройки интеграции сохранены.",
        }

    # ------------------------------------------------------------------
    # Runtime helpers (used by flow / inbound workers)
    # ------------------------------------------------------------------

    async def create_calendar_event(
        self,
        bot: Bot,
        *,
        summary: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        attendee_email: str | None = None,
        client_phone: str | None = None,
    ) -> dict[str, Any]:
        from app.services.integrations.google_calendar_service import create_calendar_event as gcal_create

        config = _reveal_block("google_calendar", self._read_integration(bot, "google_calendar"))
        if not config.get("connected"):
            raise ValueError("Google Calendar is not connected.")
        return await gcal_create(
            bot,
            title=summary,
            start_iso=start_iso,
            end_iso=end_iso,
            client_email=attendee_email,
            client_phone=client_phone or description,
            config=config,
        )

    async def check_calendar_availability(
        self,
        bot: Bot,
        *,
        start_iso: str,
        end_iso: str,
    ) -> dict[str, Any]:
        from app.services.integrations.google_calendar_service import check_calendar_availability

        config = _reveal_block("google_calendar", self._read_integration(bot, "google_calendar"))
        if not config.get("connected"):
            raise ValueError("Google Calendar is not connected.")
        return await check_calendar_availability(bot, start_iso=start_iso, end_iso=end_iso, config=config)

    async def create_kaspi_invoice(
        self,
        bot: Bot,
        *,
        amount_kzt: float,
        order_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        config = _reveal_block("kaspi_pay", self._read_integration(bot, "kaspi_pay"))
        if not config.get("connected"):
            raise ValueError("Kaspi Pay is not connected.")
        # Merchant deep-link / payment URL pattern used by Kaspi Business partners.
        merchant_id = str(config.get("merchant_id") or "")
        base = str(config.get("payment_base_url") or "https://pay.kaspi.kz/pay")
        query = urlencode(
            {
                "service": merchant_id,
                "amount": f"{amount_kzt:.2f}",
                "orderId": order_id,
                "desc": description[:120],
            }
        )
        payment_url = f"{base}?{query}"
        return {
            "order_id": order_id,
            "amount_kzt": amount_kzt,
            "payment_url": payment_url,
            "merchant_id": merchant_id,
            "status": "created",
        }

    async def verify_kaspi_receipt_text(self, text: str) -> dict[str, Any]:
        from app.services.ocr_service import parse_kaspi_receipt_text

        data = parse_kaspi_receipt_text(text)
        return {
            "transaction_id": data.transaction_id,
            "amount": str(data.amount) if data.amount is not None else None,
            "is_complete": data.is_complete,
            "source": data.source,
        }

    async def verify_kaspi_receipt_file(
        self, file_bytes: bytes, filename: str
    ) -> dict[str, Any]:
        from app.services.ocr_service import extract_kaspi_receipt_data

        data = extract_kaspi_receipt_data(file_bytes, filename)
        if data is None:
            return {"transaction_id": None, "amount": None, "is_complete": False, "source": "none"}
        return {
            "transaction_id": data.transaction_id,
            "amount": str(data.amount) if data.amount is not None else None,
            "is_complete": data.is_complete,
            "source": data.source,
        }

    async def create_uon_lead(
        self,
        bot: Bot,
        *,
        name: str,
        phone: str = "",
        email: str = "",
        note: str = "",
        destination: str = "",
        budget: str = "",
    ) -> dict[str, Any]:
        config = _reveal_block("uon", self._read_integration(bot, "uon"))
        if not config.get("connected"):
            raise ValueError("U-ON is not connected.")
        api_key = str(config.get("api_key") or "")
        base = str(config.get("base_url") or "https://api.u-on.ru").rstrip("/")
        payload = {
            "r_u_name": name,
            "r_u_phone": phone,
            "r_u_email": email,
            "r_note": note,
            "r_tour_to": destination,
            "r_price": budget,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{base}/{api_key}/lead/create.json",
                data=payload,
            )
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return {"ok": True, "raw": response.text[:500]}

    async def send_jivo_message(
        self,
        bot: Bot,
        *,
        client_id: str,
        text: str,
    ) -> dict[str, Any]:
        config = _reveal_block("jivo", self._read_integration(bot, "jivo"))
        if not config.get("connected"):
            raise ValueError("Jivo is not connected.")
        token = str(config.get("token") or config.get("api_key") or "")
        provider_id = str(config.get("provider_id") or "moonai")
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"https://bot.jivosite.com/webhooks/{provider_id}/{token}",
                json={
                    "sender": {"id": "moonai-bot"},
                    "message": {"type": "text", "text": text},
                    "chat_id": client_id,
                },
            )
            response.raise_for_status()
            return {"ok": True, "status_code": response.status_code}

    # ------------------------------------------------------------------
    # Connect implementations
    # ------------------------------------------------------------------

    async def _connect_amocrm(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: dict[str, Any],
        *,
        storage_platform: str = "amocrm",
    ) -> dict[str, Any]:
        from app.schemas.crm_schemas import AmoCRMConnectRequest
        from app.services.crm_integration_service import crm_integration_service

        result = await crm_integration_service.connect_amocrm(
            db,
            bot.id,
            AmoCRMConnectRequest(
                base_domain=str(payload.get("base_domain") or ""),
                client_id=str(payload.get("client_id") or ""),
                client_secret=str(payload.get("client_secret") or ""),
                authorization_code=str(payload.get("authorization_code") or ""),
                redirect_uri=payload.get("redirect_uri"),
            ),
        )
        if storage_platform == "kommo":
            self._write_integration(
                bot,
                "kommo",
                {
                    "connected": result.connected,
                    "sync_enabled": result.sync_enabled,
                    "base_domain": str(payload.get("base_domain") or ""),
                    "connected_at": _now_iso(),
                    "updated_at": _now_iso(),
                },
            )
        return {
            "bot_id": str(bot.id),
            "platform": storage_platform,
            "connected": result.connected,
            "sync_enabled": result.sync_enabled,
            "message": result.message,
        }

    async def _connect_bitrix(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        from app.schemas.crm_schemas import Bitrix24ConnectRequest
        from app.services.crm_integration_service import crm_integration_service

        result = await crm_integration_service.connect_bitrix24(
            db,
            bot.id,
            Bitrix24ConnectRequest(webhook_url=str(payload.get("webhook_url") or "")),
        )
        return {
            "bot_id": str(bot.id),
            "platform": "bitrix24",
            "connected": result.connected,
            "sync_enabled": result.sync_enabled,
            "message": result.message,
        }

    async def _connect_custom_webhook(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        target_url = str(payload.get("webhook_target_url") or payload.get("webhook_url") or "").strip()
        if not target_url.startswith("https://"):
            raise ValueError("Укажите HTTPS URL для custom webhook.")
        secret = str(payload.get("hmac_secret") or payload.get("webhook_secret") or generate_webhook_secret())
        config = {
            "connected": True,
            "sync_enabled": True,
            "webhook_target_url": target_url,
            "hmac_secret": secret,
            "connected_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write_integration(bot, "custom_webhook", config)
        await db.flush()
        return {
            "bot_id": str(bot.id),
            "platform": "custom_webhook",
            "connected": True,
            "sync_enabled": True,
            "message": "Custom webhook подключён.",
        }

    async def _connect_google_calendar(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        refresh_token = str(payload.get("refresh_token") or "").strip()
        access_token = str(payload.get("access_token") or "").strip()
        client_id = str(payload.get("client_id") or getattr(settings, "GOOGLE_CLIENT_ID", "") or "").strip()
        client_secret = str(
            payload.get("client_secret") or getattr(settings, "GOOGLE_CLIENT_SECRET", "") or ""
        ).strip()
        calendar_id = str(payload.get("calendar_id") or "primary").strip() or "primary"

        if not refresh_token and not access_token:
            raise ValueError("Укажите OAuth refresh_token или access_token Google Calendar.")

        # Validate token by listing calendars when access_token present.
        if access_token:
            async with httpx.AsyncClient(timeout=15.0) as client:
                probe = await client.get(
                    "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"maxResults": 1},
                )
                if probe.status_code >= 400:
                    raise ValueError("Google Calendar access_token отклонён API.")

        config = {
            "connected": True,
            "sync_enabled": True,
            "refresh_token": refresh_token,
            "access_token": access_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "calendar_id": calendar_id,
            "connected_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write_integration(bot, "google_calendar", config)
        await db.flush()
        return {
            "bot_id": str(bot.id),
            "platform": "google_calendar",
            "connected": True,
            "sync_enabled": True,
            "message": "Google Calendar подключён.",
        }

    async def _connect_kaspi_receipts(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        # Bot-side receipt verification uses the platform OCR engine; optional API key
        # reserved for future Kaspi Business verification API.
        config = {
            "connected": True,
            "sync_enabled": True,
            "mode": str(payload.get("mode") or "ocr"),
            "api_key": str(payload.get("api_key") or ""),
            "min_amount_kzt": float(payload.get("min_amount_kzt") or 0),
            "connected_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write_integration(bot, "kaspi_receipts", config)
        await db.flush()
        return {
            "bot_id": str(bot.id),
            "platform": "kaspi_receipts",
            "connected": True,
            "sync_enabled": True,
            "message": "Проверка Kaspi-чеков включена для агента.",
        }

    async def _connect_kaspi_pay(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        merchant_id = str(payload.get("merchant_id") or "").strip()
        if not merchant_id:
            raise ValueError("Укажите Merchant ID Kaspi Pay / Kaspi Business.")
        config = {
            "connected": True,
            "sync_enabled": True,
            "merchant_id": merchant_id,
            "merchant_token": str(payload.get("merchant_token") or payload.get("api_key") or ""),
            "secret_key": str(payload.get("secret_key") or ""),
            "payment_base_url": str(payload.get("payment_base_url") or "https://pay.kaspi.kz/pay"),
            "connected_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write_integration(bot, "kaspi_pay", config)
        await db.flush()
        return {
            "bot_id": str(bot.id),
            "platform": "kaspi_pay",
            "connected": True,
            "sync_enabled": True,
            "message": "Kaspi Pay подключён. Агент может выставлять счета в диалоге.",
        }

    async def _connect_jivo(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        token = str(payload.get("token") or payload.get("api_key") or "").strip()
        provider_id = str(payload.get("provider_id") or "moonai").strip() or "moonai"
        if len(token) < 8:
            raise ValueError("Укажите токен канала Jivo (Bot API).")
        webhook_secret = generate_webhook_secret()
        webhook_url = (
            f"{resolve_webhook_base_url()}/api/v1/webhooks/jivo/{bot.id}"
        )
        config = {
            "connected": True,
            "sync_enabled": True,
            "token": token,
            "provider_id": provider_id,
            "webhook_secret": webhook_secret,
            "webhook_url": webhook_url,
            "connected_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write_integration(bot, "jivo", config)
        await db.flush()
        return {
            "bot_id": str(bot.id),
            "platform": "jivo",
            "connected": True,
            "sync_enabled": True,
            "webhook_url": webhook_url,
            "message": "Jivo подключён. Укажите webhook URL в кабинете Jivo.",
        }

    async def _connect_uon(
        self, db: AsyncSession, bot: Bot, payload: dict[str, Any]
    ) -> dict[str, Any]:
        api_key = str(payload.get("api_key") or "").strip()
        if len(api_key) < 8:
            raise ValueError("Укажите API-ключ U-ON.Travel.")
        base_url = str(payload.get("base_url") or "https://api.u-on.ru").rstrip("/")
        # Lightweight validate — U-ON returns JSON or error page.
        async with httpx.AsyncClient(timeout=15.0) as client:
            probe = await client.get(f"{base_url}/{api_key}/manager.json")
            if probe.status_code in {401, 403}:
                raise ValueError("API-ключ U-ON отклонён.")
        config = {
            "connected": True,
            "sync_enabled": True,
            "api_key": api_key,
            "base_url": base_url,
            "connected_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._write_integration(bot, "uon", config)
        await db.flush()
        return {
            "bot_id": str(bot.id),
            "platform": "uon",
            "connected": True,
            "sync_enabled": True,
            "message": "U-ON подключён. Заявки туристов будут создаваться как лиды.",
        }

    async def _ensure_google_access_token(self, bot: Bot, config: dict[str, Any]) -> str:
        token = str(config.get("access_token") or "").strip()
        if token:
            return token
        refresh = str(config.get("refresh_token") or "").strip()
        client_id = str(config.get("client_id") or getattr(settings, "GOOGLE_CLIENT_ID", "") or "")
        client_secret = str(
            config.get("client_secret") or getattr(settings, "GOOGLE_CLIENT_SECRET", "") or ""
        )
        if not refresh or not client_id or not client_secret:
            raise ValueError("Google Calendar OAuth credentials incomplete.")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()
        access = str(data.get("access_token") or "")
        if not access:
            raise ValueError("Google failed to refresh access_token.")
        config["access_token"] = access
        config["updated_at"] = _now_iso()
        # Persist refreshed token (best-effort; caller may not have a session).
        try:
            from app.core.database import async_session_factory

            async with async_session_factory() as db:
                fresh = await db.get(Bot, bot.id)
                if fresh is not None:
                    self._write_integration(fresh, "google_calendar", config)
                    await db.commit()
        except Exception as exc:
            logger.warning(
                "Integrations.google_token_persist_failed | bot_id={bot_id} error={error}",
                bot_id=bot.id,
                error=str(exc),
            )
        return access

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _status_for(self, bot: Bot, platform: str) -> dict[str, Any]:
        labels = {
            "amocrm": "amoCRM",
            "kommo": "Kommo",
            "bitrix24": "Битрикс 24",
            "google_calendar": "Google Calendar",
            "kaspi_receipts": "Проверка Kaspi-чеков",
            "kaspi_pay": "Kaspi Pay",
            "custom_webhook": "Custom Integration",
            "jivo": "Jivo",
            "uon": "U-ON",
        }
        if platform == "kommo":
            cfg = _reveal_block("kommo", self._read_integration(bot, "kommo"))
            if not cfg.get("connected"):
                crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
                amo_cfg = reveal_amocrm_config(crm.get("amocrm") if isinstance(crm, dict) else None) or {}
                if amo_cfg.get("base_domain", "").endswith("kommo.com"):
                    cfg = amo_cfg
            connected = bool(cfg.get("connected"))
            return {
                "platform": platform,
                "connected": connected,
                "sync_enabled": bool(cfg.get("sync_enabled", True)) if connected else False,
                "label": labels[platform],
                "detail": cfg.get("base_domain"),
                "availability": "available",
                "webhook_url": None,
                "meta": {"pipeline_id": cfg.get("pipeline_id"), "stage_id": cfg.get("stage_id")},
            }
        if platform == "amocrm":
            crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
            cfg = reveal_amocrm_config(crm.get("amocrm") if isinstance(crm, dict) else None) or {}
            connected = bool(cfg.get("connected") or get_amocrm_access_token(bot))
            return {
                "platform": platform,
                "connected": connected,
                "sync_enabled": bool(cfg.get("sync_enabled", True)) if connected else False,
                "label": labels[platform],
                "detail": cfg.get("base_domain"),
                "availability": "available",
                "webhook_url": None,
                "meta": {"pipeline_id": cfg.get("pipeline_id"), "stage_id": cfg.get("stage_id")},
            }
        if platform == "bitrix24":
            crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
            cfg = reveal_bitrix_config(crm.get("bitrix24") if isinstance(crm, dict) else None) or {}
            connected = bool(cfg.get("connected") or get_bitrix_webhook_url(bot))
            return {
                "platform": platform,
                "connected": connected,
                "sync_enabled": bool(cfg.get("sync_enabled", True)) if connected else False,
                "label": labels[platform],
                "detail": None,
                "availability": "available",
                "webhook_url": None,
                "meta": {"pipeline_id": cfg.get("pipeline_id"), "stage_id": cfg.get("stage_id")},
            }

        cfg = _reveal_block(platform, self._read_integration(bot, platform))
        connected = bool(cfg.get("connected"))
        return {
            "platform": platform,
            "connected": connected,
            "sync_enabled": bool(cfg.get("sync_enabled", True)) if connected else False,
            "label": labels.get(platform, platform),
            "detail": cfg.get("calendar_id")
            or cfg.get("merchant_id")
            or cfg.get("provider_id")
            or None,
            "availability": "available",
            "webhook_url": cfg.get("webhook_url"),
            "meta": {
                k: cfg.get(k)
                for k in ("calendar_id", "merchant_id", "mode", "provider_id")
                if cfg.get(k)
            },
        }

    def _read_integration(self, bot: Bot, platform: str) -> dict[str, Any]:
        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        block = credentials.get("integrations")
        if not isinstance(block, dict):
            return {}
        entry = block.get(platform)
        return dict(entry) if isinstance(entry, dict) else {}

    def _write_integration(self, bot: Bot, platform: str, config: dict[str, Any]) -> None:
        credentials = dict(bot.credentials or {})
        integrations = dict(credentials.get("integrations") or {})
        if not config:
            integrations.pop(platform, None)
        else:
            integrations[platform] = _seal_block(platform, config)
        credentials["integrations"] = integrations
        bot.credentials = credentials

    async def _require_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        bot = await db.get(Bot, bot_id)
        if bot is None:
            raise ValueError("Bot not found.")
        return bot


bot_app_integrations_service = BotAppIntegrationsService()

