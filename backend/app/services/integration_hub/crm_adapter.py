"""CRMAdapter — Bitrix24 / amoCRM operations used by agents (architecture §3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.services.integration_hub.http import hub_request
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle


class AuthExpiredError(Exception):
    """401/403 from the provider — connection should move to ``expired``."""


@dataclass
class CRMContact:
    id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None


@dataclass
class CRMDeal:
    id: str
    title: str | None = None
    stage_id: str | None = None
    contact_id: str | None = None


class CRMAdapter(Protocol):
    """Python counterpart of the TypeScript CRMAdapter (see frontend types)."""

    provider: str

    async def test_connection(self, *, secrets: TokenBundle, http: httpx.AsyncClient, connection_id: UUID) -> bool: ...

    async def create_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> CRMContact: ...

    async def update_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        contact_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> CRMContact: ...

    async def find_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        phone: str | None = None,
        email: str | None = None,
        query: str | None = None,
    ) -> CRMContact | None: ...

    async def create_deal(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        title: str,
        contact_id: str | None = None,
        stage_id: str | None = None,
    ) -> CRMDeal: ...

    async def update_deal_stage(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        deal_id: str,
        stage_id: str,
    ) -> CRMDeal: ...

    async def add_note(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        entity_type: str,
        entity_id: str,
        text: str,
    ) -> None: ...

    async def refresh_token(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle: ...


def _raise_if_auth(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise AuthExpiredError("Provider rejected the access token.")
    response.raise_for_status()


class AmoCRMAdapter:
    provider = "amocrm"

    def _hub(self):
        from app.services.integration_hub.adapters.amocrm import AmoCRMHubAdapter

        return AmoCRMHubAdapter()

    async def test_connection(self, *, secrets: TokenBundle, http: httpx.AsyncClient, connection_id: UUID) -> bool:
        from app.services.integration_hub.adapters.amocrm import AmoCRMAuthExpired

        try:
            await self._hub().rest_call(
                secrets=secrets,
                http=http,
                connection_id=connection_id,
                method="GET",
                path="/api/v4/account",
            )
            return True
        except AmoCRMAuthExpired as exc:
            raise AuthExpiredError(str(exc)) from exc

    async def create_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> CRMContact:
        result = await self._hub().create_contact(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            name=name,
            phone=phone,
            email=email,
        )
        return CRMContact(id=str(result.get("id") or ""), name=name, phone=phone, email=email)

    async def update_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        contact_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> CRMContact:
        fields: dict[str, Any] = {}
        if name:
            fields["name"] = name
        custom = []
        if phone:
            custom.append({"field_code": "PHONE", "values": [{"value": phone}]})
        if email:
            custom.append({"field_code": "EMAIL", "values": [{"value": email}]})
        if custom:
            fields["custom_fields_values"] = custom
        await self._hub().update_contact(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            contact_id=contact_id,
            fields=fields,
        )
        return CRMContact(id=contact_id, name=name, phone=phone, email=email)

    async def find_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        phone: str | None = None,
        email: str | None = None,
        query: str | None = None,
    ) -> CRMContact | None:
        q = query or phone or email or ""
        if not q:
            return None
        row = await self._hub().find_contact(
            secrets=secrets, http=http, connection_id=connection_id, query=q
        )
        if not row:
            return None
        return CRMContact(id=str(row.get("id") or ""), name=row.get("name"))

    async def create_deal(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        title: str,
        contact_id: str | None = None,
        stage_id: str | None = None,
    ) -> CRMDeal:
        result = await self._hub().create_lead(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            title=title,
            contact_id=contact_id,
            stage_id=stage_id,
        )
        return CRMDeal(
            id=str(result.get("id") or ""),
            title=title,
            stage_id=stage_id,
            contact_id=contact_id,
        )

    async def update_deal_stage(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        deal_id: str,
        stage_id: str,
    ) -> CRMDeal:
        await self._hub().update_lead_stage(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            lead_id=deal_id,
            stage_id=stage_id,
        )
        return CRMDeal(id=deal_id, stage_id=stage_id)

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
        await self._hub().add_note(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            entity_type=entity_type,
            entity_id=entity_id,
            text=text,
        )

    async def refresh_token(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        db: Any = None,
        connection: Any = None,
    ) -> TokenBundle:
        """Rotate tokens. When ``db`` + ``connection`` are set, take the one-time-token lock."""
        if db is not None and connection is not None:
            from app.services.integration_hub.oauth import secrets_from_connection_with_vault
            from app.services.integration_hub.service import integration_hub_service

            row = await integration_hub_service.refresh_connection(
                db,
                connection,
                http=http,
                expected_refresh_token=secrets.refresh_token,
            )
            return await secrets_from_connection_with_vault(db, row)
        from app.services.integration_hub.adapters.amocrm import AmoCRMHubAdapter

        return await AmoCRMHubAdapter().refresh(platform_app=platform_app, secrets=secrets, http=http)


class Bitrix24Adapter:
    provider = "bitrix24"

    def _hub(self):
        from app.services.integration_hub.adapters.bitrix24 import Bitrix24HubAdapter

        return Bitrix24HubAdapter()

    async def test_connection(self, *, secrets: TokenBundle, http: httpx.AsyncClient, connection_id: UUID) -> bool:
        from app.services.integration_hub.adapters.bitrix24 import BitrixAuthExpired

        try:
            if (secrets.extra or {}).get("auth_mode") == "webhook":
                base = (
                    secrets.webhook_url or str((secrets.extra or {}).get("webhook_url") or "")
                ).rstrip("/")
                if not base:
                    return False
                response = await http.get(f"{base}/profile.json", timeout=15.0)
                return 200 <= response.status_code < 400
            await self._hub().rest_call(
                secrets=secrets,
                http=http,
                connection_id=connection_id,
                method="user.current",
                params={},
            )
            return True
        except BitrixAuthExpired as exc:
            raise AuthExpiredError(str(exc)) from exc

    async def create_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> CRMContact:
        result = await self._hub().create_contact(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            name=name,
            phone=phone,
            email=email,
        )
        return CRMContact(id=str(result.get("id") or ""), name=name, phone=phone, email=email)

    async def update_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        contact_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> CRMContact:
        fields: dict[str, Any] = {}
        if name:
            fields["NAME"] = name
        if phone:
            fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
        if email:
            fields["EMAIL"] = [{"VALUE": email, "VALUE_TYPE": "WORK"}]
        await self._hub().update_contact(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            contact_id=contact_id,
            fields=fields,
        )
        return CRMContact(id=contact_id, name=name, phone=phone, email=email)

    async def find_contact(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        phone: str | None = None,
        email: str | None = None,
        query: str | None = None,
    ) -> CRMContact | None:
        filt: dict[str, Any] = {}
        if phone:
            filt["PHONE"] = phone
        elif email:
            filt["EMAIL"] = email
        elif query:
            filt["NAME"] = query
        else:
            return None
        rows = await self._hub().list_contacts(
            secrets=secrets, http=http, connection_id=connection_id, filter_fields=filt
        )
        if not rows:
            return None
        row = rows[0]
        return CRMContact(id=str(row.get("ID") or row.get("id") or ""), name=row.get("NAME"))

    async def create_deal(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        title: str,
        contact_id: str | None = None,
        stage_id: str | None = None,
    ) -> CRMDeal:
        result = await self._hub().create_deal(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            title=title,
            contact_id=contact_id,
            stage_id=stage_id,
        )
        return CRMDeal(
            id=str(result.get("id") or ""),
            title=title,
            stage_id=stage_id,
            contact_id=contact_id,
        )

    async def update_deal_stage(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        deal_id: str,
        stage_id: str,
    ) -> CRMDeal:
        await self._hub().update_deal(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            deal_id=deal_id,
            fields={"STAGE_ID": stage_id},
        )
        return CRMDeal(id=deal_id, stage_id=stage_id)

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
        await self._hub().add_note(
            secrets=secrets,
            http=http,
            connection_id=connection_id,
            entity_type=entity_type,
            entity_id=entity_id,
            text=text,
        )

    async def refresh_token(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        return await self._hub().refresh(platform_app=platform_app, secrets=secrets, http=http)


_CRM: dict[str, CRMAdapter] = {
    "amocrm": AmoCRMAdapter(),
    "kommo": AmoCRMAdapter(),
    "bitrix24": Bitrix24Adapter(),
}


def get_crm_adapter(provider: str) -> CRMAdapter | None:
    return _CRM.get((provider or "").strip().lower())
