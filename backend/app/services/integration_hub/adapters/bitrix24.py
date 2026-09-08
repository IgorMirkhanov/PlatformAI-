"""Bitrix24 mass-market adapter — OAuth via oauth.bitrix.info, REST per client portal."""

from __future__ import annotations

import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from app.core.config import resolve_webhook_base_url
from app.services.integration_hub.bitrix_portal import (
    BitrixPortalRateLimited,
    acquire_bitrix_portal_slot,
    portal_rate_key,
)
from app.services.integration_hub.rate_limit import acquire_bitrix_connection_slot
from app.services.integration_hub.http import hub_request
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle

# Mass-market OAuth lives on the Bitrix OAuth server, never on the client portal.
# Isolated on-prem portals often cannot proxy /oauth/token to Bitrix's cloud.
OAUTH_AUTHORIZE_URL = "https://oauth.bitrix.info/oauth/authorize/"
OAUTH_TOKEN_URL = "https://oauth.bitrix.info/oauth/token/"

CRM_EVENT_HANDLERS = (
    "ONAPPINSTALL",
    "ONAPPUNINSTALL",
    "ONCRMDEALADD",
    "ONCRMDEALUPDATE",
    "ONCRMCONTACTADD",
    "ONCRMCONTACTUPDATE",
)

_AUTH_ERRORS = frozenset(
    {"expired_token", "invalid_token", "NO_AUTH_FOUND", "insufficient_scope", "ACCESS_DENIED"}
)


class BitrixAuthExpired(Exception):
    """OAuth access token rejected — refresh or re-install."""


class Bitrix24HubAdapter:
    """Marketplace / mass-market app (status F/D/T/P), not a local incoming webhook app."""

    provider = "bitrix24"

    def authorize_url(self, *, client_id: str, redirect_uri: str, state: str, domain: str | None = None) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        # Optional hint only — host is always oauth.bitrix.info.
        if domain:
            params["domain"] = domain.replace("https://", "").replace("http://", "").split("/")[0]
        return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        webhook = str(payload.get("webhook_url") or "").strip()
        code = str(payload.get("authorization_code") or payload.get("code") or "").strip()
        if webhook:
            url = webhook.rstrip("/") + "/profile.json"
            response = await http.get(url, timeout=15.0)
            if response.status_code >= 400:
                raise ValueError("Bitrix24 webhook URL отклонён.")
            return TokenBundle(
                webhook_url=webhook.rstrip("/") + "/",
                extra={"auth_mode": "webhook"},
                external_account_id=webhook.split("/")[-2] if "/" in webhook else webhook[:32],
            )
        if platform_app is None or not platform_app.client_id or not platform_app.client_secret:
            raise ValueError("Platform Bitrix24 OAuth app is not configured.")
        if not code:
            raise ValueError("Для Bitrix24 нужен OAuth authorization code.")
        data = await self._exchange_code(platform_app=platform_app, code=code, http=http, redirect_uri=payload.get("redirect_uri"))
        return self._bundle_from_oauth(data)

    async def test_connection(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> bool:
        """Validate webhook or OAuth credentials with a lightweight profile call."""
        del connection_id
        if (secrets.extra or {}).get("auth_mode") == "webhook" or secrets.webhook_url:
            endpoint = self._rest_endpoint(secrets)
            response = await http.get(f"{endpoint}profile.json", timeout=15.0)
            return response.status_code < 400
        if not secrets.access_token:
            return False
        endpoint = self._rest_endpoint(secrets)
        response = await http.get(
            f"{endpoint}profile.json",
            params={"auth": secrets.access_token},
            timeout=15.0,
        )
        return response.status_code < 400

    async def refresh(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        if (secrets.extra or {}).get("auth_mode") == "webhook":
            return secrets
        if platform_app is None or not secrets.refresh_token:
            raise ValueError("Cannot refresh Bitrix24 OAuth: missing refresh_token.")
        response = await http.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": platform_app.client_id,
                "client_secret": platform_app.client_secret,
                "refresh_token": secrets.refresh_token,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        parsed = response.json()
        data = parsed if isinstance(parsed, dict) else {}
        return self._bundle_from_oauth(data, previous=secrets)

    async def _exchange_code(
        self,
        *,
        platform_app: PlatformOAuthApp,
        code: str,
        http: httpx.AsyncClient,
        redirect_uri: Any = None,
    ) -> dict[str, Any]:
        response = await http.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": platform_app.client_id,
                "client_secret": platform_app.client_secret,
                "code": code,
                "redirect_uri": redirect_uri or platform_app.redirect_uri,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _bundle_from_oauth(self, data: dict[str, Any], previous: TokenBundle | None = None) -> TokenBundle:
        extra = dict(previous.extra) if previous else {}
        extra["auth_mode"] = "oauth"
        for key in ("domain", "member_id", "client_endpoint", "server_endpoint", "status", "scope"):
            if data.get(key):
                extra[key] = data.get(key)
        if data.get("application_token"):
            extra["application_token"] = data["application_token"]
        elif previous and previous.extra.get("application_token"):
            extra["application_token"] = previous.extra["application_token"]
        expires_in = int(data.get("expires_in") or 3600)
        domain = str(extra.get("domain") or (previous.external_account_id if previous else "") or "")
        return TokenBundle(
            access_token=str(data.get("access_token") or (previous.access_token if previous else "") or "") or None,
            refresh_token=str(data.get("refresh_token") or (previous.refresh_token if previous else "") or "") or None,
            extra=extra,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in)),
            external_account_id=str(extra.get("member_id") or domain) or None,
        )

    def _rest_endpoint(self, secrets: TokenBundle) -> str:
        webhook = (secrets.webhook_url or str(secrets.extra.get("webhook_url") or "")).strip()
        if webhook:
            return webhook.rstrip("/") + "/"
        client_endpoint = str(secrets.extra.get("client_endpoint") or "").strip()
        if client_endpoint:
            return client_endpoint if client_endpoint.endswith("/") else client_endpoint + "/"
        domain = str(secrets.extra.get("domain") or secrets.external_account_id or "").strip()
        domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{domain}/rest/"

    def _portal_key(self, secrets: TokenBundle, connection_id: UUID) -> str:
        return portal_rate_key(
            str(secrets.extra.get("member_id") or "") or None,
            str(secrets.extra.get("domain") or "") or None,
            str(connection_id),
        )

    async def rest_call(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call a REST method on the client portal; token ops never go through this path.

        Portal leaky-bucket is 2 req/s (non-Enterprise). Do not retry in a hot loop:
        raise ``BitrixPortalRateLimited`` so the caller enqueues (Celery).
        """
        if method in {"crm.deal.stage.list", "crm.deal.stages.list"}:
            method = "crm.dealcategory.stage.list"
        # Checklist §5: hard cap per connection_id, then portal key (shared portal safety).
        try:
            acquire_bitrix_connection_slot(connection_id)
        except Exception as exc:
            from app.services.integration_hub.rate_limit import ConnectionRateLimited

            if isinstance(exc, ConnectionRateLimited):
                raise BitrixPortalRateLimited(str(exc)) from exc
            raise
        acquire_bitrix_portal_slot(self._portal_key(secrets, connection_id))
        url = f"{self._rest_endpoint(secrets)}{method}"
        body = dict(params or {})
        if secrets.access_token and (secrets.extra or {}).get("auth_mode") != "webhook":
            body["auth"] = secrets.access_token
        response = await http.post(url, json=body, timeout=20.0)
        if response.status_code in {401, 403}:
            raise BitrixAuthExpired("Bitrix24 rejected the access token.")
        payload: Any
        try:
            payload = response.json() if response.content else {}
        except Exception:
            payload = {}
        error = str(payload.get("error") or "") if isinstance(payload, dict) else ""
        if response.status_code == 503 or error == "QUERY_LIMIT_EXCEEDED":
            raise BitrixPortalRateLimited("Bitrix24 QUERY_LIMIT_EXCEEDED.")
        if error in _AUTH_ERRORS:
            raise BitrixAuthExpired(error)
        if error:
            raise ValueError(f"Bitrix24 {method} failed: {error}")
        if response.status_code >= 400:
            response.raise_for_status()
        return payload.get("result") if isinstance(payload, dict) and "result" in payload else payload

    async def bind_event_handlers(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> None:
        if (secrets.extra or {}).get("auth_mode") == "webhook":
            return
        handler = f"{resolve_webhook_base_url()}/api/v1/webhooks/bitrix24/{connection_id}"
        for event in CRM_EVENT_HANDLERS:
            try:
                await self.rest_call(
                    secrets=secrets,
                    http=http,
                    connection_id=connection_id,
                    method="event.bind",
                    params={"EVENT": event, "HANDLER": handler},
                )
            except BitrixPortalRateLimited:
                raise
            except Exception as exc:
                logger.warning(
                    "Bitrix24.event_bind_failed | event={event} error={error}",
                    event=event,
                    error=type(exc).__name__,
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
        fields: dict[str, Any] = {"NAME": name}
        if phone:
            fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
        if email:
            fields["EMAIL"] = [{"VALUE": email, "VALUE_TYPE": "WORK"}]
        result = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.contact.add",
            params={"fields": fields},
        )
        return {"id": str(result)}

    async def update_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        contact_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.contact.update",
            params={"id": contact_id, "fields": fields},
        )
        return {"id": str(contact_id)}

    async def list_contacts(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        filter_fields: dict[str, Any] | None = None,
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.contact.list",
            params={
                "filter": filter_fields or {},
                "select": select or ["ID", "NAME", "LAST_NAME", "PHONE", "EMAIL"],
            },
        )
        return list(result or []) if isinstance(result, list) else []

    async def create_deal(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        title: str,
        contact_id: str | None = None,
        stage_id: str | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {"TITLE": title}
        if contact_id:
            fields["CONTACT_ID"] = contact_id
        if stage_id:
            fields["STAGE_ID"] = stage_id
        result = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.deal.add",
            params={"fields": fields},
        )
        return {"id": str(result)}

    async def update_deal(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        deal_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.deal.update",
            params={"id": deal_id, "fields": fields},
        )
        return {"id": str(deal_id)}

    async def list_deals(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        filter_fields: dict[str, Any] | None = None,
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.deal.list",
            params={
                "filter": filter_fields or {},
                "select": select or ["ID", "TITLE", "STAGE_ID", "CONTACT_ID"],
            },
        )
        return list(result or []) if isinstance(result, list) else []

    async def list_deal_stages(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        category_id: int = 0,
    ) -> list[dict[str, Any]]:
        # Official method is crm.dealcategory.stage.list (no crm.deal.stage.list in REST).
        result = await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.dealcategory.stage.list",
            params={"id": category_id},
        )
        return list(result or []) if isinstance(result, list) else []

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
        kind = "deal" if entity_type.lower() in {"deal", "2"} else "contact"
        await self.rest_call(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            method="crm.timeline.comment.add",
            params={
                "fields": {
                    "ENTITY_ID": entity_id,
                    "ENTITY_TYPE": kind,
                    "COMMENT": text,
                }
            },
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
        _ = secrets
        if connection_id is not None:
            try:
                acquire_bitrix_connection_slot(connection_id)
            except Exception as exc:
                from app.services.integration_hub.rate_limit import ConnectionRateLimited

                if isinstance(exc, ConnectionRateLimited):
                    raise BitrixPortalRateLimited(str(exc)) from exc
                raise
            acquire_bitrix_portal_slot(self._portal_key(secrets, connection_id))
        return await hub_request(
            http,
            connection_id=None,
            method=method,
            url=url,
            json_body=json_body,
            params=params,
        )


def parse_bitrix_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON or nested form-encoded Bitrix event bodies."""
    if not isinstance(payload, dict):
        return {}
    event = str(payload.get("event") or payload.get("EVENT") or "").upper()
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    fields = data.get("FIELDS") if isinstance(data.get("FIELDS"), dict) else data
    return {
        "event": event,
        "ts": str(payload.get("ts") or payload.get("TS") or ""),
        "entity_id": str((fields or {}).get("ID") or (fields or {}).get("id") or ""),
        "application_token": str(auth.get("application_token") or ""),
        "member_id": str(auth.get("member_id") or ""),
        "domain": str(auth.get("domain") or ""),
        "auth": auth,
        "data": data,
    }


def verify_application_token(*, stored: str | None, provided: str | None) -> bool:
    expected = (stored or "").strip()
    got = (provided or "").strip()
    if not expected or not got:
        return False
    return pysecrets.compare_digest(expected, got)


def flatten_form_dict(form: dict[str, Any]) -> dict[str, Any]:
    """Turn ``auth[application_token]`` keys into nested dicts."""
    tree: dict[str, Any] = {}
    for raw_key, value in form.items():
        key = str(raw_key)
        if "[" not in key:
            tree[key] = value
            continue
        parts = key.replace("]", "").split("[")
        cursor: dict[str, Any] = tree
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = value
    return tree
