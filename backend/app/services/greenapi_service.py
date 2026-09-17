"""Green API (WhatsApp / Instagram) REST client — probe, webhook, send, poll."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.utils.phone_utils import clean_phone_number

_AUTHORIZED = frozenset({"authorized", "sleepmode", "sleepMode"})


class GreenApiError(ValueError):
    """Tenant-visible Green API failure."""


def greenapi_base_url() -> str:
    return (settings.WHATSAPP_GREENAPI_API_URL or "https://api.green-api.com").rstrip("/")


def greenapi_method_url(instance_id: str, method: str, token: str) -> str:
    return f"{greenapi_base_url()}/waInstance{instance_id.strip()}/{method}/{token.strip()}"


def normalize_greenapi_chat_id(chat_id: str) -> str:
    raw = (chat_id or "").strip()
    if not raw:
        raise GreenApiError("Пустой chatId Green API.")
    if "@" in raw:
        return raw
    cleaned = clean_phone_number(raw)
    digits = (cleaned or "").lstrip("+") or "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    return f"{digits}@c.us"


class GreenApiService:
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0))

    async def get_state(self, instance_id: str, token: str) -> str:
        url = greenapi_method_url(instance_id, "getStateInstance", token)
        async with self._client() as http:
            response = await http.get(url)
        if response.status_code >= 400:
            raise GreenApiError(
                "Green API отклонил Instance ID / API Token. Проверьте данные в кабинете green-api.com."
            )
        try:
            body = response.json()
        except Exception as exc:
            raise GreenApiError("Green API вернул не-JSON при проверке инстанса.") from exc
        state = str((body or {}).get("stateInstance") or "").strip()
        return state

    async def assert_authorized(self, instance_id: str, token: str) -> str:
        instance = (instance_id or "").strip()
        secret = (token or "").strip()
        if instance in {"1101234567"} or not instance.isdigit():
            raise GreenApiError(
                "Instance ID — это ваш idInstance из кабинета green-api.com, не пример и не email."
            )
        if len(secret) < 8:
            raise GreenApiError("API Token Green API слишком короткий.")
        try:
            state = await self.get_state(instance, secret)
        except GreenApiError:
            raise
        except httpx.RequestError as exc:
            raise GreenApiError(f"Green API недоступен: {exc}") from exc
        if state.lower() not in {item.lower() for item in _AUTHORIZED}:
            raise GreenApiError(
                "Инстанс Green API не авторизован. В кабинете green-api.com отсканируйте QR "
                "или используйте кнопку «Подключить по QR-коду» для личного WhatsApp."
            )
        return state

    async def set_webhook_url(self, instance_id: str, token: str, webhook_url: str) -> None:
        url = greenapi_method_url(instance_id, "setSettings", token)
        payload = {
            "webhookUrl": webhook_url,
            "incomingWebhook": "yes",
            "outgoingWebhook": "no",
            "stateWebhook": "no",
        }
        async with self._client() as http:
            response = await http.post(url, json=payload)
        if response.status_code >= 400:
            raise GreenApiError("Не удалось зарегистрировать webhook в Green API.")

    async def send_text(self, instance_id: str, token: str, chat_id: str, text: str) -> None:
        url = greenapi_method_url(instance_id, "sendMessage", token)
        payload = {"chatId": normalize_greenapi_chat_id(chat_id), "message": (text or "")[:4096]}
        async with self._client() as http:
            response = await http.post(url, json=payload)
        if response.status_code >= 400:
            logger.error(
                "GreenApi.send_failed | status={status} body={body}",
                status=response.status_code,
                body=(response.text or "")[:400],
            )
            raise GreenApiError("Green API не отправил сообщение.")

    async def receive_notification(self, instance_id: str, token: str) -> dict[str, Any] | None:
        url = greenapi_method_url(instance_id, "receiveNotification", token)
        async with self._client() as http:
            response = await http.get(url)
        if response.status_code >= 400:
            return None
        try:
            body = response.json()
        except Exception:
            return None
        if not isinstance(body, dict) or not body:
            return None
        return body

    async def delete_notification(self, instance_id: str, token: str, receipt_id: int) -> None:
        url = greenapi_method_url(instance_id, "deleteNotification", token)
        async with self._client() as http:
            await http.delete(f"{url}/{receipt_id}")


greenapi_service = GreenApiService()
