"""CRM adapters — amoCRM OAuth + Bitrix24 webhook/OAuth (architecture spec §8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlencode

from loguru import logger

from app.core.config import settings
from app.core.metrics import record_crm_lead


class BaseCRMAdapter(ABC):
    crm_id: str = "base"

    @abstractmethod
    async def create_lead(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def find_contact_by_phone(self, phone: str) -> dict[str, Any] | None:
        return None

    async def add_note(self, external_lead_id: str, text: str) -> dict[str, Any] | None:
        """Optional timeline note on an existing lead. Default is a no-op."""
        return None


class AmoCRMAdapter(BaseCRMAdapter):
    crm_id = "amocrm"

    def authorize_url(self, *, subdomain: str, state: str, redirect_uri: str | None = None) -> str:
        client_id = (settings.AMOCRM_CLIENT_ID or "").strip()
        redirect = (redirect_uri or settings.AMOCRM_REDIRECT_URI or "").strip()
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "state": state,
                "mode": "post_message",
            }
        )
        host = subdomain.strip().rstrip("/")
        if not host.endswith(".amocrm.ru") and "." not in host:
            host = f"{host}.amocrm.ru"
        return f"https://{host}/oauth?{params}"

    async def exchange_code(self, *, subdomain: str, code: str) -> dict[str, Any]:
        import httpx

        url = f"https://{subdomain.strip()}/oauth2/access_token"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                json={
                    "client_id": settings.AMOCRM_CLIENT_ID,
                    "client_secret": settings.AMOCRM_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.AMOCRM_REDIRECT_URI,
                },
            )
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, dict) else {}

    async def create_lead(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.integrations.crm_service import save_lead_to_crm_integration

        bot = payload.get("bot")
        db = payload.get("db")
        if bot is None or db is None:
            record_crm_lead("amocrm", "skipped")
            return {"status": "skipped", "reason": "bot_or_db_missing"}
        try:
            result = await save_lead_to_crm_integration(
                db,
                bot=bot,
                phone=payload.get("phone"),
                client_name=payload.get("name"),
                comment=payload.get("comment"),
                channel=str(payload.get("channel") or "web"),
                channel_user_id=payload.get("channel_user_id"),
            )
            record_crm_lead("amocrm", "ok")
            return result if isinstance(result, dict) else {"status": "ok"}
        except Exception as exc:
            record_crm_lead("amocrm", "error")
            logger.warning("AmoCRMAdapter.create_lead_failed | error={error}", error=str(exc))
            raise

    async def find_contact_by_phone(self, phone: str) -> dict[str, Any] | None:
        return None


class Bitrix24Adapter(BaseCRMAdapter):
    crm_id = "bitrix24"

    def __init__(self, webhook_url: str | None = None, oauth_token: str | None = None) -> None:
        self.webhook_url = (webhook_url or "").rstrip("/") + ("/" if webhook_url else "")
        self.oauth_token = oauth_token

    async def create_lead(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        title = str(payload.get("title") or payload.get("name") or "Lead")
        fields = {
            "TITLE": title,
            "NAME": payload.get("name") or title,
            "PHONE": [{"VALUE": payload.get("phone"), "VALUE_TYPE": "WORK"}]
            if payload.get("phone")
            else [],
            "COMMENTS": payload.get("comment") or "",
        }
        try:
            if self.webhook_url:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(
                        f"{self.webhook_url}crm.lead.add",
                        json={"fields": fields},
                    )
                    response.raise_for_status()
                    data = response.json()
            elif self.oauth_token:
                portal = str(payload.get("portal") or getattr(settings, "BITRIX_PORTAL_URL", "") or "")
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(
                        f"{portal.rstrip('/')}/rest/crm.lead.add",
                        params={"auth": self.oauth_token},
                        json={"fields": fields},
                    )
                    response.raise_for_status()
                    data = response.json()
            else:
                record_crm_lead("bitrix24", "skipped")
                return {"status": "skipped", "reason": "no_webhook_or_oauth"}
            record_crm_lead("bitrix24", "ok")
            return data if isinstance(data, dict) else {"status": "ok"}
        except Exception as exc:
            record_crm_lead("bitrix24", "error")
            logger.warning("Bitrix24Adapter.create_lead_failed | error={error}", error=str(exc))
            raise


def get_crm_adapter(crm: str, **kwargs: Any) -> BaseCRMAdapter:
    key = (crm or "").strip().lower()
    if key in {"amocrm", "amo", "kommo"}:
        return AmoCRMAdapter()
    if key in {"bitrix", "bitrix24"}:
        return Bitrix24Adapter(
            webhook_url=kwargs.get("webhook_url"),
            oauth_token=kwargs.get("oauth_token"),
        )
    raise ValueError(f"Unsupported CRM adapter: {crm}")
