from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.models.core_models import Bot, ChatMessage, Client, DiagnosticErrorType, MessageSender
from app.models.integrations import (
    reveal_amocrm_config,
    reveal_bitrix_config,
    seal_amocrm_config,
    seal_bitrix_config,
)
from app.schemas.crm_schemas import CRMActionPayload
from app.services.diagnostic_log_service import diagnostic_log_service
from app.utils.phone_utils import clean_phone_number

CRM_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
AMOCRM_TOKEN_PATH = "/oauth2/access_token"
DEFAULT_CRM_TAGS: tuple[str, ...] = ("ai_lead", "mp_ai")


class CRMTransientError(RuntimeError):
    """Rate-limit / timeout / temporary CRM API failure — safe for Celery retry."""


class CRMPermanentError(RuntimeError):
    """Non-retriable CRM failure (auth, validation, missing config)."""


class CRMOrchestrator:
    """Production async CRM engine for amoCRM and Bitrix24."""

    _shared_client: httpx.AsyncClient | None = None

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._external_client = http_client

    def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if CRMOrchestrator._shared_client is None or CRMOrchestrator._shared_client.is_closed:
            CRMOrchestrator._shared_client = httpx.AsyncClient(
                timeout=CRM_HTTP_TIMEOUT,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
            )
        return CRMOrchestrator._shared_client

    async def execute_crm_action(
        self,
        bot_id: uuid.UUID,
        client_id: uuid.UUID,
        action_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Match contact, create lead/deal, attach chat summary note.

        Transient CRM API failures raise ``CRMTransientError`` so Celery can retry.
        Permanent failures are logged to ``BotDiagnosticLogs`` as ``CRM_DISCONNECT``.
        """
        async with async_session_factory() as db:
            try:
                return await self._execute_crm_action(db, bot_id, client_id, action_data)
            except CRMTransientError:
                raise
            except Exception as exc:
                logger.exception(
                    "CRMOrchestrator.execute_failed | bot_id={bot_id} client_id={client_id} error={error}",
                    bot_id=bot_id,
                    client_id=client_id,
                    error=str(exc),
                )
                node_id = str(action_data.get("node_id") or "")
                await diagnostic_log_service.log(
                    db,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=DiagnosticErrorType.CRM_DISCONNECT,
                    error_message=str(exc),
                    node_id=node_id or None,
                )
                await db.commit()
                return {"success": False, "error": str(exc)}

    async def load_active_crm_credentials(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        platform: str | None = None,
    ) -> dict[str, Any]:
        """Return CRM credential blocks where ``sync_enabled`` is true."""
        bot = await self._load_bot(db, bot_id)
        crm = (bot.credentials or {}).get("crm") or {}
        active: dict[str, Any] = {}
        for key, config in crm.items():
            if not isinstance(config, dict):
                continue
            if platform and key.lower() != platform.lower():
                continue
            if not self._is_crm_sync_enabled(bot, key):
                continue
            active[key] = {
                "sync_enabled": True,
                "base_domain": config.get("base_domain"),
                "webhook_configured": bool(config.get("webhook_url")),
                "pipeline_id": config.get("pipeline_id"),
                "stage_id": config.get("stage_id"),
                "default_tags": config.get("default_tags") or list(DEFAULT_CRM_TAGS),
                "has_access_token": bool(config.get("access_token")),
                "connected": bool(config.get("connected")),
            }
        return active

    async def _execute_crm_action(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        client_id: uuid.UUID,
        action_data: dict[str, Any],
    ) -> dict[str, Any]:
        bot = await self._load_bot(db, bot_id)
        client = await self._load_client(db, client_id)

        try:
            payload = CRMActionPayload.model_validate(action_data)
            normalized = payload.model_dump(mode="json")
        except ValidationError as exc:
            raise CRMPermanentError(f"Invalid CRM action payload: {exc}") from exc

        platform = str(normalized.get("platform") or "amocrm").lower()
        normalized = self._merge_default_crm_tags(bot, platform, normalized)

        active = await self.load_active_crm_credentials(db, bot_id, platform=platform)
        if platform not in active:
            return {
                "success": False,
                "error": f"{platform} CRM sync is disabled or not connected for this bot.",
            }

        try:
            if platform == "bitrix24":
                return await self._execute_bitrix24(db, bot, client, normalized)
            return await self._execute_amocrm(db, bot, client, normalized)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code == 429 or status_code >= 500:
                raise CRMTransientError(
                    f"{platform} temporary HTTP {status_code}: {exc}"
                ) from exc
            raise CRMPermanentError(f"{platform} HTTP {status_code}: {exc}") from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
            raise CRMTransientError(f"{platform} network failure: {exc}") from exc

    async def exchange_amocrm_tokens(
        self,
        db: AsyncSession,
        bot: Bot,
        *,
        base_domain: str,
        client_id: str,
        client_secret: str,
        authorization_code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        domain = self._normalize_amocrm_domain(base_domain)
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": redirect_uri,
        }
        token_data = await self._amocrm_token_request(domain, payload)
        await self._persist_amocrm_tokens(
            db,
            bot,
            domain=domain,
            client_id=client_id,
            client_secret=client_secret,
            token_data=token_data,
        )
        await db.commit()
        return token_data

    async def connect_bitrix24(
        self,
        db: AsyncSession,
        bot: Bot,
        webhook_url: str,
    ) -> None:
        normalized = webhook_url.rstrip("/") + "/"
        async with self._client() as client:
            response = await client.get(f"{normalized}app.info.json")
            response.raise_for_status()
            body = response.json()
            if body.get("error"):
                raise ValueError(body.get("error_description") or body.get("error"))

        credentials = dict(bot.credentials or {})
        crm = dict(credentials.get("crm") or {})
        crm["bitrix24"] = seal_bitrix_config(
            {
                "webhook_url": normalized,
                "connected": True,
                "sync_enabled": True,
                "connected_at": datetime.now(UTC).isoformat(),
            }
        )
        credentials["crm"] = crm
        bot.credentials = credentials
        await db.commit()

    async def get_integration_status(self, bot: Bot) -> list[dict[str, Any]]:
        crm = (bot.credentials or {}).get("crm") or {}
        amo = crm.get("amocrm") or {}
        bitrix = crm.get("bitrix24") or {}
        amo_connected = bool(amo.get("connected") and amo.get("access_token"))
        bitrix_connected = bool(bitrix.get("connected") and bitrix.get("webhook_url"))
        return [
            {
                "platform": "amocrm",
                "connected": amo_connected,
                "sync_enabled": bool(amo.get("sync_enabled", amo_connected)),
                "label": "amoCRM",
                "detail": amo.get("base_domain"),
                "pipeline_id": amo.get("pipeline_id"),
                "stage_id": amo.get("stage_id"),
                "default_tags": amo.get("default_tags") or [],
            },
            {
                "platform": "bitrix24",
                "connected": bitrix_connected,
                "sync_enabled": bool(bitrix.get("sync_enabled", bitrix_connected)),
                "label": "Bitrix24",
                "detail": "webhook configured" if bitrix_connected else None,
                "pipeline_id": bitrix.get("pipeline_id"),
                "stage_id": bitrix.get("stage_id"),
                "default_tags": bitrix.get("default_tags") or [],
            },
        ]

    async def patch_integration(
        self,
        db: AsyncSession,
        bot: Bot,
        platform: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = platform.lower()
        if normalized not in {"amocrm", "bitrix24"}:
            raise ValueError(f"Unsupported CRM platform '{platform}'.")

        if normalized == "amocrm":
            auth_code = payload.get("authorization_code")
            if auth_code:
                await self.exchange_amocrm_tokens(
                    db,
                    bot,
                    base_domain=str(payload.get("base_domain") or ""),
                    client_id=str(payload.get("client_id") or ""),
                    client_secret=str(payload.get("client_secret") or ""),
                    authorization_code=str(auth_code),
                    redirect_uri=str(payload.get("redirect_uri") or "https://localhost/oauth"),
                )
            await self._apply_integration_settings(db, bot, "amocrm", payload)
        else:
            webhook = payload.get("webhook_url")
            if webhook:
                await self.connect_bitrix24(db, bot, str(webhook))
            await self._apply_integration_settings(db, bot, "bitrix24", payload)

        await db.commit()
        statuses = await self.get_integration_status(bot)
        current = next(item for item in statuses if item["platform"] == normalized)
        return {
            "bot_id": bot.id,
            "platform": normalized,
            "connected": current["connected"],
            "sync_enabled": current["sync_enabled"],
            "message": "CRM integration settings saved.",
        }

    async def _apply_integration_settings(
        self,
        db: AsyncSession,
        bot: Bot,
        platform: str,
        payload: dict[str, Any],
    ) -> None:
        credentials = dict(bot.credentials or {})
        crm = dict(credentials.get("crm") or {})
        config = dict(crm.get(platform) or {})

        if payload.get("sync_enabled") is not None:
            config["sync_enabled"] = bool(payload["sync_enabled"])
        if payload.get("pipeline_id") is not None:
            config["pipeline_id"] = str(payload["pipeline_id"])
        if payload.get("stage_id") is not None:
            config["stage_id"] = str(payload["stage_id"])
        if payload.get("default_tags") is not None:
            config["default_tags"] = [str(tag).strip() for tag in payload["default_tags"] if str(tag).strip()]

        crm[platform] = config
        credentials["crm"] = crm
        bot.credentials = credentials
        await db.flush()

    async def list_pipelines(
        self,
        db: AsyncSession,
        bot: Bot,
        platform: str,
    ) -> list[dict[str, str]]:
        normalized = platform.lower()
        if normalized == "bitrix24":
            return await self._list_bitrix_pipelines(bot)
        return await self._list_amocrm_pipelines(db, bot)

    async def _execute_amocrm(
        self,
        db: AsyncSession,
        bot: Bot,
        client: Client,
        action_data: dict[str, Any],
    ) -> dict[str, Any]:
        config = await self._get_amocrm_config(db, bot)
        if not config:
            return {"success": False, "error": "amoCRM is not connected for this bot."}

        domain = config["base_domain"]
        headers = await self._amocrm_auth_headers(db, bot, config)
        query = self._client_lookup_query(client)

        async with self._client() as http:
            contact_id = await self._amocrm_find_or_create_contact(http, domain, headers, client, query)
            lead_id = await self._amocrm_create_lead(
                http,
                domain,
                headers,
                contact_id=contact_id,
                action_data=action_data,
            )
            summary = self._build_message_summary(client.messages)
            await self._amocrm_attach_note(http, domain, headers, lead_id, summary)

        logger.info(
            "CRMOrchestrator.amocrm_success | bot_id={bot_id} client_id={client_id} lead_id={lead_id}",
            bot_id=bot.id,
            client_id=client.id,
            lead_id=lead_id,
        )
        return {
            "success": True,
            "platform": "amocrm",
            "contact_id": contact_id,
            "lead_id": lead_id,
        }

    async def _execute_bitrix24(
        self,
        db: AsyncSession,
        bot: Bot,
        client: Client,
        action_data: dict[str, Any],
    ) -> dict[str, Any]:
        webhook = self._get_bitrix_webhook(bot)
        if not webhook:
            return {"success": False, "error": "Bitrix24 is not connected for this bot."}

        query = self._client_lookup_query(client)
        async with self._client() as http:
            contact_id = await self._bitrix_find_or_create_contact(http, webhook, client, query)
            deal_id = await self._bitrix_create_deal(http, webhook, contact_id, action_data)
            summary = self._build_message_summary(client.messages)
            await self._bitrix_attach_timeline_comment(http, webhook, deal_id, summary)

        logger.info(
            "CRMOrchestrator.bitrix_success | bot_id={bot_id} client_id={client_id} deal_id={deal_id}",
            bot_id=bot.id,
            client_id=client.id,
            deal_id=deal_id,
        )
        return {
            "success": True,
            "platform": "bitrix24",
            "contact_id": contact_id,
            "deal_id": deal_id,
        }

    async def _amocrm_find_or_create_contact(
        self,
        http: httpx.AsyncClient,
        domain: str,
        headers: dict[str, str],
        client: Client,
        query: str,
    ) -> int:
        search = await http.get(
            f"https://{domain}/api/v4/contacts",
            params={"query": query, "limit": 1},
            headers=headers,
        )
        search.raise_for_status()
        embedded = search.json().get("_embedded") or {}
        contacts = embedded.get("contacts") or []
        if contacts:
            return int(contacts[0]["id"])

        name = client.first_name or client.username or f"Client {client.external_id}"
        payload = [
            {
                "name": name,
                "custom_fields_values": self._amocrm_contact_fields(client, query),
            }
        ]
        create = await http.post(
            f"https://{domain}/api/v4/contacts",
            headers=headers,
            json=payload,
        )
        if create.status_code in {400, 422}:
            # Parallel create race — re-query by phone/telegram before failing.
            retry = await http.get(
                f"https://{domain}/api/v4/contacts",
                params={"query": query, "limit": 1},
                headers=headers,
            )
            retry.raise_for_status()
            retry_contacts = (retry.json().get("_embedded") or {}).get("contacts") or []
            if retry_contacts:
                return int(retry_contacts[0]["id"])
        create.raise_for_status()
        created = (create.json().get("_embedded") or {}).get("contacts") or []
        if not created:
            raise ValueError("amoCRM contact creation returned empty payload.")
        return int(created[0]["id"])

    async def _amocrm_create_lead(
        self,
        http: httpx.AsyncClient,
        domain: str,
        headers: dict[str, str],
        *,
        contact_id: int,
        action_data: dict[str, Any],
    ) -> int:
        pipeline_id = action_data.get("pipeline_id")
        status_id = action_data.get("stage_id") or action_data.get("status_id")
        tags = action_data.get("tags") or []
        custom_attributes = action_data.get("custom_attributes") or {}
        if not isinstance(custom_attributes, dict):
            custom_attributes = {}

        lead_name = str(custom_attributes.get("lead_name") or f"MP.Ai Lead #{contact_id}")
        lead_body: dict[str, Any] = {
            "name": lead_name,
            "_embedded": {"contacts": [{"id": contact_id}]},
        }
        if pipeline_id is not None and str(pipeline_id).strip():
            lead_body["pipeline_id"] = int(pipeline_id)
        if status_id is not None and str(status_id).strip():
            lead_body["status_id"] = int(status_id)
        if tags:
            lead_body["tags_to_add"] = [{"name": str(tag)} for tag in tags if str(tag).strip()]

        # Persist conversational custom attributes as a common note-friendly field dump.
        attribute_lines = [
            f"{key}: {value}"
            for key, value in custom_attributes.items()
            if key != "lead_name" and value is not None and str(value).strip()
        ]
        if attribute_lines:
            lead_body["custom_fields_values"] = lead_body.get("custom_fields_values") or []

        response = await http.post(
            f"https://{domain}/api/v4/leads",
            headers=headers,
            json=[lead_body],
        )
        response.raise_for_status()
        leads = (response.json().get("_embedded") or {}).get("leads") or []
        if not leads:
            raise ValueError("amoCRM lead creation returned empty payload.")
        lead_id = int(leads[0]["id"])

        if attribute_lines:
            await self._amocrm_attach_note(
                http,
                domain,
                headers,
                lead_id,
                "MP.Ai custom attributes:\n" + "\n".join(attribute_lines),
            )
        return lead_id

    async def _amocrm_attach_note(
        self,
        http: httpx.AsyncClient,
        domain: str,
        headers: dict[str, str],
        lead_id: int,
        summary: str,
    ) -> None:
        payload = [
            {
                "entity_id": lead_id,
                "note_type": "common",
                "params": {"text": summary},
            }
        ]
        response = await http.post(
            f"https://{domain}/api/v4/leads/notes",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

    async def _bitrix_find_or_create_contact(
        self,
        http: httpx.AsyncClient,
        webhook: str,
        client: Client,
        query: str,
    ) -> int:
        cleaned = clean_phone_number(query)
        if not cleaned:
            raise ValueError("Bitrix24 contact requires a valid phone number.")
        contact_id = await self._bitrix_find_or_create_contact_safe(
            http,
            webhook,
            name=client.first_name or client.username or "Клиент",
            phone=cleaned,
            external_id=client.external_id,
        )
        if contact_id is None:
            raise ValueError("Bitrix24 contact creation failed — invalid phone.")
        return contact_id

    async def _bitrix_create_deal(
        self,
        http: httpx.AsyncClient,
        webhook: str,
        contact_id: int,
        action_data: dict[str, Any],
    ) -> int:
        tags = [str(tag).strip() for tag in (action_data.get("tags") or []) if str(tag).strip()]
        custom_attributes = action_data.get("custom_attributes") or {}
        if not isinstance(custom_attributes, dict):
            custom_attributes = {}

        attribute_blob = "; ".join(
            f"{key}={value}"
            for key, value in custom_attributes.items()
            if value is not None and str(value).strip()
        )
        comments_parts = []
        if tags:
            comments_parts.append("Tags: " + ", ".join(tags))
        if attribute_blob:
            comments_parts.append("Attrs: " + attribute_blob)

        fields: dict[str, Any] = {
            "TITLE": str(custom_attributes.get("lead_name") or f"MP.Ai Deal #{contact_id}"),
            "CONTACT_ID": contact_id,
            "SOURCE_ID": "OTHER",
        }
        if comments_parts:
            fields["COMMENTS"] = " | ".join(comments_parts)

        stage_id = action_data.get("stage_id") or action_data.get("STAGE_ID")
        pipeline_id = action_data.get("pipeline_id")
        if stage_id:
            fields["STAGE_ID"] = stage_id
        if pipeline_id is not None and str(pipeline_id).strip():
            fields["CATEGORY_ID"] = int(pipeline_id)

        response = await http.post(
            f"{webhook}crm.deal.add",
            json={"fields": fields},
        )
        if response.status_code in {400, 422}:
            logger.error(
                "Bitrix24.payload_sent | endpoint=crm.deal.add payload={payload}",
                payload={"fields": fields},
            )
            logger.error(
                "Bitrix24.error_response | status={status} body={body}",
                status=response.status_code,
                body=response.text[:2000],
            )
        response.raise_for_status()
        deal_id = response.json().get("result")
        if not deal_id:
            raise ValueError("Bitrix24 deal creation returned empty result.")
        return int(deal_id)

    async def _bitrix_attach_timeline_comment(
        self,
        http: httpx.AsyncClient,
        webhook: str,
        deal_id: int,
        summary: str,
    ) -> None:
        response = await http.post(
            f"{webhook}crm.timeline.comment.add",
            json={
                "fields": {
                    "ENTITY_ID": deal_id,
                    "ENTITY_TYPE": "deal",
                    "COMMENT": summary,
                }
            },
        )
        response.raise_for_status()

    async def _list_amocrm_pipelines(
        self,
        db: AsyncSession,
        bot: Bot,
    ) -> list[dict[str, str]]:
        config = await self._get_amocrm_config(db, bot)
        if not config:
            return []

        domain = config["base_domain"]
        headers = await self._amocrm_auth_headers(db, bot, config)
        async with self._client() as http:
            response = await http.get(
                f"https://{domain}/api/v4/leads/pipelines",
                headers=headers,
            )
            response.raise_for_status()
            pipelines = (response.json().get("_embedded") or {}).get("pipelines") or []

        stages: list[dict[str, str]] = []
        for pipeline in pipelines:
            pipeline_id = str(pipeline.get("id"))
            pipeline_name = str(pipeline.get("name") or pipeline_id)
            for status in pipeline.get("_embedded", {}).get("statuses", []):
                stages.append(
                    {
                        "id": str(status.get("id")),
                        "name": str(status.get("name") or status.get("id")),
                        "pipeline_id": pipeline_id,
                        "pipeline_name": pipeline_name,
                    }
                )
        return stages

    async def _list_bitrix_pipelines(self, bot: Bot) -> list[dict[str, str]]:
        webhook = self._get_bitrix_webhook(bot)
        if not webhook:
            return []

        stages: list[dict[str, str]] = []
        async with self._client() as http:
            categories = await http.get(f"{webhook}crm.dealcategory.list")
            categories.raise_for_status()
            for category in categories.json().get("result") or []:
                category_id = str(category.get("ID"))
                category_name = str(category.get("NAME") or category_id)
                stage_resp = await http.get(
                    f"{webhook}crm.dealcategory.stage.list",
                    params={"id": category_id},
                )
                stage_resp.raise_for_status()
                for stage in stage_resp.json().get("result") or []:
                    stages.append(
                        {
                            "id": str(stage.get("STATUS_ID")),
                            "name": str(stage.get("NAME") or stage.get("STATUS_ID")),
                            "pipeline_id": category_id,
                            "pipeline_name": category_name,
                        }
                    )
        return stages

    async def _amocrm_auth_headers(
        self,
        db: AsyncSession,
        bot: Bot,
        config: dict[str, Any],
    ) -> dict[str, str]:
        expires_at = config.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at))
                if expiry <= datetime.now(UTC) + timedelta(minutes=2):
                    await self._refresh_amocrm_token(db, bot, config)
                    config = await self._get_amocrm_config(db, bot) or config
            except ValueError:
                logger.warning("CRMOrchestrator.invalid_amocrm_expiry | bot_id={bot_id}", bot_id=bot.id)

        token = config.get("access_token")
        if not token:
            raise ValueError("amoCRM access token is missing.")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _refresh_amocrm_token(
        self,
        db: AsyncSession,
        bot: Bot,
        config: dict[str, Any],
    ) -> None:
        from app.core.pg_locks import LOCK_NS_CRM_OAUTH, pg_advisory_xact_lock_uuid

        # Serialize refreshes per bot — amoCRM rotates refresh tokens.
        await pg_advisory_xact_lock_uuid(db, LOCK_NS_CRM_OAUTH, bot.id)

        # Re-read sealed config under the lock in case another worker already refreshed.
        fresh = await self._get_amocrm_config(db, bot) or config
        expires_at = fresh.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at))
                if expiry > datetime.now(UTC) + timedelta(minutes=2):
                    return
            except ValueError:
                pass

        domain = fresh["base_domain"]
        refresh_token = fresh.get("refresh_token") or config.get("refresh_token")
        if not refresh_token:
            raise ValueError("amoCRM refresh_token is missing; reconnect OAuth.")

        payload = {
            "client_id": fresh.get("client_id") or config["client_id"],
            "client_secret": fresh.get("client_secret") or config["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": fresh.get("redirect_uri")
            or config.get("redirect_uri", "https://localhost/oauth"),
        }
        token_data = await self._amocrm_token_request(domain, payload)
        # Preserve previous refresh_token when amoCRM omits a rotation.
        if not token_data.get("refresh_token"):
            token_data = {**token_data, "refresh_token": refresh_token}
        await self._persist_amocrm_tokens(
            db,
            bot,
            domain=domain,
            client_id=str(payload["client_id"]),
            client_secret=str(payload["client_secret"]),
            token_data=token_data,
            redirect_uri=str(payload["redirect_uri"]),
            previous_refresh_token=refresh_token,
        )
        await db.commit()

    async def _amocrm_token_request(self, domain: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._client() as http:
            response = await http.post(f"https://{domain}{AMOCRM_TOKEN_PATH}", json=payload)
            response.raise_for_status()
            body = response.json()
            if "access_token" not in body:
                raise ValueError(body.get("hint") or body.get("title") or "amoCRM token exchange failed.")
            return body

    async def _persist_amocrm_tokens(
        self,
        db: AsyncSession,
        bot: Bot,
        *,
        domain: str,
        client_id: str,
        client_secret: str,
        token_data: dict[str, Any],
        redirect_uri: str = "https://localhost/oauth",
        previous_refresh_token: str | None = None,
    ) -> None:
        expires_in = int(token_data.get("expires_in") or 86400)
        expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
        credentials = dict(bot.credentials or {})
        crm = dict(credentials.get("crm") or {})
        refresh = (
            token_data.get("refresh_token")
            or previous_refresh_token
            or ""
        )
        if not refresh:
            raise ValueError("amoCRM refresh_token missing after token exchange.")
        # Seal OAuth secrets with AES-256-GCM before JSONB persistence.
        crm["amocrm"] = seal_amocrm_config(
            {
                "base_domain": domain,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "access_token": token_data["access_token"],
                "refresh_token": refresh,
                "expires_at": expires_at,
                "connected": True,
                "sync_enabled": True,
                "connected_at": datetime.now(UTC).isoformat(),
            }
        )
        credentials["crm"] = crm
        bot.credentials = credentials
        await db.flush()

    async def _get_amocrm_config(self, db: AsyncSession, bot: Bot) -> dict[str, Any] | None:
        crm = (bot.credentials or {}).get("crm") or {}
        config = crm.get("amocrm")
        if not isinstance(config, dict) or not config.get("connected"):
            return None
        # Transparent decrypt for Celery / sync workers.
        return reveal_amocrm_config(config)

    def _get_bitrix_webhook(self, bot: Bot) -> str | None:
        crm = (bot.credentials or {}).get("crm") or {}
        config = reveal_bitrix_config(crm.get("bitrix24") if isinstance(crm.get("bitrix24"), dict) else None)
        if not config:
            return None
        url = config.get("webhook_url")
        if config.get("connected") and isinstance(url, str) and url.strip():
            return url.rstrip("/") + "/"
        return None

    async def _load_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            raise ValueError(f"Bot '{bot_id}' not found.")
        return bot

    async def _load_client(self, db: AsyncSession, client_id: uuid.UUID) -> Client:
        result = await db.execute(
            select(Client)
            .where(Client.id == client_id)
            .options(selectinload(Client.messages))
        )
        client = result.scalar_one_or_none()
        if client is None:
            raise ValueError(f"Client '{client_id}' not found.")
        return client

    def _client_lookup_query(self, client: Client) -> str:
        for message in reversed(client.messages or []):
            payload = message.payload or {}
            phone = payload.get("phone") or payload.get("phone_number")
            cleaned = clean_phone_number(str(phone) if phone else None)
            if cleaned:
                return cleaned
        if client.username:
            cleaned = clean_phone_number(client.username)
            if cleaned:
                return cleaned
            return client.username
        cleaned = clean_phone_number(client.external_id)
        return cleaned or client.external_id

    async def _bitrix_api_add(
        self,
        http: httpx.AsyncClient,
        webhook: str,
        method: str,
        payload: dict[str, Any],
    ) -> int:
        """POST to Bitrix24 REST ``method``; log payload + body on 400/422."""
        response = await http.post(f"{webhook}{method}", json=payload)
        if response.status_code in {400, 422}:
            logger.error(
                "Bitrix24.payload_sent | endpoint={endpoint} payload={payload}",
                endpoint=method,
                payload=payload,
            )
            logger.error(
                "Bitrix24.error_response | status={status} body={body}",
                status=response.status_code,
                body=response.text[:2000],
            )
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            raise ValueError(f"Bitrix24 {method} returned empty result.")
        return int(result)

    async def _bitrix_find_or_create_contact_safe(
        self,
        http: httpx.AsyncClient,
        webhook: str,
        *,
        name: str,
        phone: str,
        external_id: str,
        payload_sent: dict[str, Any] | None = None,
    ) -> int | None:
        cleaned = clean_phone_number(phone)
        if not cleaned:
            return None
        try:
            search = await http.get(
                f"{webhook}crm.contact.list",
                params={"filter[PHONE]": cleaned, "select[]": ["ID", "NAME"]},
            )
            if search.status_code in {400, 422}:
                logger.error(
                    "Bitrix24.payload_sent | endpoint=crm.contact.list filter[PHONE]={phone}",
                    phone=cleaned,
                )
                logger.error(
                    "Bitrix24.error_response | status={status} body={body}",
                    status=search.status_code,
                    body=search.text[:2000],
                )
            search.raise_for_status()
            result = search.json().get("result") or []
            if result:
                return int(result[0]["ID"])

            create_payload = {
                "fields": {
                    "NAME": name or "Клиент",
                    "PHONE": [{"VALUE": cleaned, "VALUE_TYPE": "WORK"}],
                    "COMMENTS": f"MP.Ai ID: {external_id}",
                }
            }
            return await self._bitrix_api_add(http, webhook, "crm.contact.add", create_payload)
        except httpx.HTTPStatusError:
            if payload_sent:
                logger.error(
                    "Bitrix24.payload_sent | endpoint=crm.contact.add payload={payload}",
                    payload=payload_sent,
                )
            raise

    def _build_message_summary(self, messages: list[ChatMessage]) -> str:
        recent = sorted(messages, key=lambda item: item.created_at)[-10:]
        lines = ["MP.Ai — последние сообщения:"]
        for message in recent:
            sender = message.sender.value if isinstance(message.sender, MessageSender) else str(message.sender)
            text = (message.message_text or "").strip()
            if not text:
                continue
            lines.append(f"[{sender}] {text}")
        return "\n".join(lines) if len(lines) > 1 else "MP.Ai — история сообщений пуста."

    def _amocrm_contact_fields(self, client: Client, query: str) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        if query and query.replace("+", "").isdigit():
            fields.append(
                {
                    "field_code": "PHONE",
                    "values": [{"value": query, "enum_code": "WORK"}],
                }
            )
        if client.username:
            fields.append(
                {
                    "field_code": "IM",
                    "values": [{"value": client.username, "enum_code": "OTHER"}],
                }
            )
        return fields

    def _is_crm_sync_enabled(self, bot: Bot, platform: str) -> bool:
        crm = (bot.credentials or {}).get("crm") or {}
        config = crm.get(platform.lower()) or {}
        if platform.lower() == "amocrm":
            connected = bool(config.get("connected") and config.get("access_token"))
        else:
            connected = bool(config.get("connected") and config.get("webhook_url"))
        if not connected:
            return False
        return bool(config.get("sync_enabled", True))

    def _merge_default_crm_tags(
        self,
        bot: Bot,
        platform: str,
        action_data: dict[str, Any],
    ) -> dict[str, Any]:
        crm = (bot.credentials or {}).get("crm") or {}
        config = crm.get(platform.lower()) or {}
        merged = dict(action_data)

        configured_defaults = config.get("default_tags") or []
        if not isinstance(configured_defaults, list):
            configured_defaults = []
        default_tags = [
            *(str(tag) for tag in DEFAULT_CRM_TAGS),
            *(str(tag) for tag in configured_defaults),
        ]

        existing = merged.get("tags") or []
        if not isinstance(existing, list):
            existing = [str(existing)] if existing else []

        custom_attributes = merged.get("custom_attributes") or {}
        if not isinstance(custom_attributes, dict):
            custom_attributes = {}
        runtime_tags = custom_attributes.get("tags")
        if isinstance(runtime_tags, list):
            existing = [*existing, *(str(tag) for tag in runtime_tags)]

        merged["tags"] = list(
            dict.fromkeys(
                tag.strip()
                for tag in [*(str(item) for item in existing), *default_tags]
                if str(tag).strip()
            )
        )
        if not merged.get("pipeline_id") and config.get("pipeline_id"):
            merged["pipeline_id"] = config["pipeline_id"]
        if not merged.get("stage_id") and config.get("stage_id"):
            merged["stage_id"] = config["stage_id"]
        merged["custom_attributes"] = custom_attributes
        return merged

    def _normalize_amocrm_domain(self, base_domain: str) -> str:
        domain = base_domain.strip().lower().replace("https://", "").replace("http://", "").strip("/")
        if not domain.endswith(".amocrm.ru") and ".amocrm." not in domain:
            domain = f"{domain}.amocrm.ru"
        return domain

    async def refresh_credential_row(self, db: AsyncSession, row: Any) -> None:
        """Refresh amoCRM/Bitrix OAuth on a vault credential under the caller's advisory lock."""
        from datetime import datetime, timedelta, timezone

        from app.services.crypto_service import current_key_version, decrypt_payload, encrypt_payload

        payload = decrypt_payload(
            row.encrypted_payload,
            row.encryption_iv,
            row.encryption_tag,
            key_version=int(row.key_version or 1),
        )
        kind = str(getattr(row, "kind", "") or "")
        if kind != "crm_amocrm":
            raise ValueError(f"OAuth refresh not implemented for kind={kind}")

        domain = self._normalize_amocrm_domain(
            str(payload.get("base_domain") or payload.get("subdomain") or "")
        )
        refresh_token = str(payload.get("refresh_token") or "")
        if not domain or not refresh_token:
            raise ValueError("amoCRM credential is missing subdomain/refresh_token.")

        token_data = await self._amocrm_token_request(
            domain,
            {
                "client_id": payload.get("client_id") or "",
                "client_secret": payload.get("client_secret") or "",
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": payload.get("redirect_uri") or "https://localhost/oauth",
            },
        )
        merged = {
            **payload,
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token") or refresh_token,
            "base_domain": domain,
        }
        ciphertext, iv, tag = encrypt_payload(merged)
        row.encrypted_payload = ciphertext
        row.encryption_iv = iv
        row.encryption_tag = tag
        row.key_version = current_key_version()
        expires_in = int(token_data.get("expires_in") or 3600)
        row.oauth_expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in))
        row.last_error = None
        row.status = "active"
        await db.flush()

    async def handle_new_message_for_crm(
        self,
        db: AsyncSession,
        *,
        bot: Bot,
        client: Client,
        message_text: str,
        channel_type: str,
        external_chat_id: str,
    ) -> dict[str, Any] | None:
        """
        Idempotent native-CRM deal upsert + optional external CRM lead.

        Failures are logged and never raised — messenger reply must already be independent.
        """
        org_id = getattr(bot, "organization_id", None)
        if org_id is None:
            return None
        try:
            from app.repositories.crm.deal_repository import compute_dedup_key, deal_repository
            from app.services.crm.pipeline_service import pipeline_service

            pipeline = await pipeline_service.create_default_pipeline(db, org_id)
            stages = sorted(pipeline.stages or [], key=lambda s: s.position)
            open_stage = next((s for s in stages if not s.is_won and not s.is_lost), None)
            if open_stage is None and stages:
                open_stage = stages[0]
            if open_stage is None:
                logger.warning("CRM.handle_new_message_no_stage | org={org}", org=org_id)
                return None

            dedup = compute_dedup_key(org_id, channel_type, external_chat_id)
            title = (client.first_name or client.username or external_chat_id or "Lead")[:255]
            result = await deal_repository(db, organization_id=org_id).upsert_idempotent(
                organization_id=org_id,
                dedup_key=dedup,
                title=title,
                pipeline_id=pipeline.id,
                stage_id=open_stage.id,
                bot_id=bot.id,
                crm_integration_id=getattr(bot, "crm_integration_id", None),
                source=channel_type[:50],
                custom_fields={
                    "conversation_id": str(client.id),
                    "external_chat_id": external_chat_id,
                    "channel_type": channel_type,
                },
            )
            if result.was_inserted:
                try:
                    from app.services.crm.adapters import get_crm_adapter

                    platform = "amocrm"
                    crm = (bot.credentials or {}).get("crm") or {}
                    if isinstance(crm, dict) and crm.get("bitrix24"):
                        platform = "bitrix24"
                    adapter = get_crm_adapter(platform)
                    await adapter.create_lead(
                        payload={
                            "bot": bot,
                            "db": db,
                            "name": title,
                            "phone": external_chat_id,
                            "comment": (message_text or "")[:2000],
                            "channel": channel_type,
                            "channel_user_id": external_chat_id,
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        "CRM.external_lead_failed | deal={deal} error={error}",
                        deal=result.deal_id,
                        error=str(exc),
                    )
            else:
                try:
                    from app.services.crm.adapters import get_crm_adapter

                    adapter = get_crm_adapter("amocrm")
                    await adapter.add_note(str(result.deal_id), (message_text or "")[:2000])
                except Exception as exc:
                    logger.debug(
                        "CRM.add_note_skipped | deal={deal} error={error}",
                        deal=result.deal_id,
                        error=str(exc),
                    )
            return {"deal_id": str(result.deal_id), "was_inserted": result.was_inserted}
        except Exception as exc:
            logger.warning(
                "CRM.handle_new_message_failed | bot_id={bot_id} error={error}",
                bot_id=bot.id,
                error=str(exc),
            )
            return None


crm_orchestrator = CRMOrchestrator()
