"""amoCRM / Kommo adapter — platform OAuth, one-time refresh_token, v4 REST."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from app.core.config import resolve_webhook_base_url
from app.services.integration_hub.amocrm_account import (
    AmoCRMAccountRateLimited,
    acquire_amocrm_account_slot,
    account_rate_key,
)
from app.services.integration_hub.http import hub_request
from app.services.integration_hub.rate_limit import acquire_amocrm_connection_slot
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle

WEBHOOK_EVENTS = (
    "add_lead",
    "update_lead",
    "status_lead",
    "add_contact",
    "update_contact",
)

_MAX_429_RETRIES = 5


class AmoCRMAuthExpired(Exception):
    """Access token rejected — refresh under advisory lock, then retry."""


class AmoCRMHubAdapter:
    """Mass-market OAuth integration (one platform app, many client accounts)."""

    provider = "amocrm"

    def _host(self, subdomain: str) -> str:
        host = (subdomain or "").strip().rstrip("/")
        host = host.replace("https://", "").replace("http://", "")
        if host.endswith(".kommo.com") or ".kommo." in host:
            return host
        if not host.endswith(".amocrm.ru") and "." not in host:
            host = f"{host}.amocrm.ru"
        return host

    def _account_key(self, secrets: TokenBundle, connection_id: UUID) -> str:
        return account_rate_key(
            str(secrets.extra.get("subdomain") or secrets.external_account_id or "") or None,
            str(connection_id),
        )

    def _base(self, secrets: TokenBundle) -> str:
        host = self._host(str(secrets.extra.get("subdomain") or secrets.external_account_id or ""))
        if host.startswith("http"):
            return host.rstrip("/")
        return f"https://{host}"

    def _headers(self, secrets: TokenBundle) -> dict[str, str]:
        token = secrets.access_token or ""
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        if platform_app is None or not platform_app.client_id or not platform_app.client_secret:
            raise ValueError("Platform amoCRM OAuth app is not configured.")
        subdomain = str(payload.get("subdomain") or payload.get("base_domain") or "").strip()
        code = str(payload.get("authorization_code") or payload.get("code") or "").strip()
        if not subdomain or not code:
            raise ValueError("Для amoCRM нужны subdomain и authorization_code.")
        host = self._host(subdomain)
        token_url = platform_app.token_url or f"https://{host}/oauth2/access_token"
        response = await http.post(
            token_url,
            json={
                "client_id": platform_app.client_id,
                "client_secret": platform_app.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": payload.get("redirect_uri") or platform_app.redirect_uri,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            data = {}
        bundle = self._bundle_from_token_response(data, host)
        try:
            acc = await http.get(
                f"https://{host}/api/v4/account",
                headers=self._headers(bundle),
                timeout=15.0,
            )
            if acc.status_code < 400:
                body = acc.json() if acc.content else {}
                if isinstance(body, dict) and body.get("id"):
                    bundle.extra["account_id"] = str(body["id"])
        except Exception:
            logger.warning("amoCRM.account_probe_failed | host={host}", host=host)
        return bundle

    async def refresh(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        """HTTP token rotation only. Callers MUST hold the connection advisory lock."""
        if platform_app is None or not secrets.refresh_token:
            raise ValueError("Cannot refresh amoCRM: missing platform app or refresh_token.")
        host = str(secrets.extra.get("subdomain") or secrets.external_account_id or "")
        token_url = platform_app.token_url or f"https://{self._host(host)}/oauth2/access_token"
        response = await http.post(
            token_url,
            json={
                "client_id": platform_app.client_id,
                "client_secret": platform_app.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": secrets.refresh_token,
                "redirect_uri": platform_app.redirect_uri,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            data = {}
        if not data.get("refresh_token"):
            data["refresh_token"] = secrets.refresh_token
        bundle = self._bundle_from_token_response(data, host)
        bundle.extra["subdomain"] = self._host(host)
        if secrets.extra.get("account_id"):
            bundle.extra["account_id"] = secrets.extra["account_id"]
        return bundle

    async def rest_call(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        method: str,
        path: str,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """v4 REST against the client account. Token exchange never goes through here."""
        url = path if path.startswith("http") else f"{self._base(secrets)}{path}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_429_RETRIES + 1):
            try:
                acquire_amocrm_connection_slot(connection_id)
                acquire_amocrm_account_slot(self._account_key(secrets, connection_id))
            except AmoCRMAccountRateLimited as exc:
                last_exc = exc
                await asyncio.sleep(min(8.0, 0.25 * (2 ** attempt)))
                continue
            except Exception as exc:
                from app.services.integration_hub.rate_limit import ConnectionRateLimited

                if isinstance(exc, ConnectionRateLimited):
                    last_exc = AmoCRMAccountRateLimited(str(exc))
                    await asyncio.sleep(min(8.0, getattr(exc, "retry_after_seconds", 0.25)))
                    continue
                raise
            response = await http.request(
                method.upper(),
                url,
                json=json_body,
                params=params,
                headers=self._headers(secrets),
                timeout=20.0,
            )
            if response.status_code in {401}:
                raise AmoCRMAuthExpired("amoCRM rejected the access token.")
            if response.status_code == 429:
                last_exc = AmoCRMAccountRateLimited("amoCRM HTTP 429")
                wait = _retry_after_seconds(response, attempt)
                logger.warning(
                    "amoCRM.http_429 | attempt={attempt} wait={wait}",
                    attempt=attempt,
                    wait=wait,
                )
                await asyncio.sleep(wait)
                continue
            if response.status_code == 403:
                raise AmoCRMAuthExpired("amoCRM API returned 403 (auth or account block).")
            if response.status_code >= 400:
                response.raise_for_status()
            if not response.content:
                return {}
            try:
                return response.json()
            except Exception:
                return {}
        raise last_exc or AmoCRMAccountRateLimited("amoCRM rate limit retries exhausted.")

    async def bind_event_handlers(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> None:
        destination = f"{resolve_webhook_base_url()}/api/v1/webhooks/amocrm/{connection_id}"
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="POST",
            path="/api/v4/webhooks",
            json_body={"destination": destination, "settings": list(WEBHOOK_EVENTS)},
        )

    async def create_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        custom: list[dict[str, Any]] = []
        if phone:
            custom.append({"field_code": "PHONE", "values": [{"value": phone}]})
        if email:
            custom.append({"field_code": "EMAIL", "values": [{"value": email}]})
        data = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="POST",
            path="/api/v4/contacts",
            json_body=[{"name": name, "custom_fields_values": custom}],
        )
        item = ((data.get("_embedded") or {}).get("contacts") or [{}])[0]
        return {"id": str(item.get("id") or "")}

    async def update_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        contact_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"id": int(contact_id), **fields}
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="PATCH",
            path="/api/v4/contacts",
            json_body=[body],
        )
        return {"id": str(contact_id)}

    async def find_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        query: str,
    ) -> dict[str, Any] | None:
        data = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="GET",
            path="/api/v4/contacts",
            params={"query": query, "limit": 1},
        )
        items = ((data.get("_embedded") or {}).get("contacts") or [])
        if not items:
            return None
        item = items[0]
        return {"id": str(item.get("id") or ""), "name": item.get("name")}

    async def create_lead(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        title: str,
        contact_id: str | None = None,
        stage_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": title}
        if stage_id:
            body["status_id"] = int(stage_id) if str(stage_id).isdigit() else stage_id
        if contact_id:
            body["_embedded"] = {"contacts": [{"id": int(contact_id)}]}
        data = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="POST",
            path="/api/v4/leads",
            json_body=[body],
        )
        item = ((data.get("_embedded") or {}).get("leads") or [{}])[0]
        return {"id": str(item.get("id") or "")}

    async def update_lead_stage(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        lead_id: str,
        stage_id: str,
    ) -> dict[str, Any]:
        status_id: Any = int(stage_id) if str(stage_id).isdigit() else stage_id
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="PATCH",
            path="/api/v4/leads",
            json_body=[{"id": int(lead_id), "status_id": status_id}],
        )
        return {"id": str(lead_id)}

    async def add_note(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        entity_type: str,
        entity_id: str,
        text: str,
    ) -> None:
        collection = "leads" if entity_type.lower() in {"deal", "lead", "leads"} else "contacts"
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="POST",
            path=f"/api/v4/{collection}/{entity_id}/notes",
            json_body=[{"note_type": "common", "params": {"text": text}}],
        )

    async def request(
        self,
        *,
        connection_id: UUID,
        secrets: TokenBundle,
        method: str,
        url: str,
        http: httpx.AsyncClient,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = self._headers(secrets)
        acquire_amocrm_connection_slot(connection_id)
        acquire_amocrm_account_slot(self._account_key(secrets, connection_id))
        return await hub_request(
            http,
            connection_id=None,
            method=method,
            url=url,
            json_body=json_body,
            params=params,
            headers=headers,
        )

    def _bundle_from_token_response(self, data: dict[str, Any], host: str) -> TokenBundle:
        expires_in = int(data.get("expires_in") or 3600)
        return TokenBundle(
            access_token=str(data.get("access_token") or "") or None,
            refresh_token=str(data.get("refresh_token") or "") or None,
            extra={"subdomain": self._host(host)},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in)),
            external_account_id=self._host(host),
        )


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    raw = (response.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return min(30.0, float(raw))
    return min(30.0, 0.5 * (2 ** attempt))


def parse_amocrm_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON or nested form-encoded amoCRM webhook bodies."""
    if not isinstance(payload, dict):
        return {"events": [], "subdomain": "", "account_id": ""}
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    events: list[dict[str, str]] = []
    for entity in ("leads", "contacts"):
        block = payload.get(entity)
        if not isinstance(block, dict):
            continue
        for action, items in block.items():
            rows = _as_item_list(items)
            for item in rows:
                if isinstance(item, dict):
                    events.append(
                        {
                            "entity": entity,
                            "action": str(action),
                            "entity_id": str(item.get("id") or ""),
                            "updated_at": str(
                                item.get("updated_at") or item.get("last_modified") or ""
                            ),
                        }
                    )
                else:
                    events.append(
                        {
                            "entity": entity,
                            "action": str(action),
                            "entity_id": str(item),
                            "updated_at": "",
                        }
                    )
    return {
        "events": events,
        "subdomain": str(account.get("subdomain") or ""),
        "account_id": str(account.get("id") or account.get("account_id") or ""),
    }


def _as_item_list(items: Any) -> list[Any]:
    if items is None:
        return []
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        if all(str(k).isdigit() for k in items):
            return [items[k] for k in sorted(items, key=lambda x: int(str(x)))]
        return [items]
    return [items]
