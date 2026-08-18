"""CRM contact service — CRUD + auto-capture from inbox Client."""

from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.core_models import Bot, Client
from app.models.crm.contact import CrmContact
from app.repositories.crm.account_repository import account_repository
from app.repositories.crm.contact_repository import contact_repository
from app.schemas.crm.accounts_contacts import (
    CrmContactCreate,
    CrmContactListResponse,
    CrmContactRead,
    CrmContactUpdate,
)


class ContactServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ContactService:
    def _contacts(self, db: AsyncSession, organization_id: uuid.UUID):
        return contact_repository(db, organization_id=organization_id)

    def _accounts(self, db: AsyncSession, organization_id: uuid.UUID):
        return account_repository(db, organization_id=organization_id)

    async def list_contacts(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        q: str | None = None,
        account_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CrmContactListResponse:
        repo = self._contacts(db, organization_id)
        items = await repo.list_filtered(
            q=q, account_id=account_id, limit=limit, offset=offset
        )
        total = await repo.count_filtered(q=q, account_id=account_id)
        return CrmContactListResponse(
            items=[CrmContactRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_contact(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> CrmContactRead:
        repo = self._contacts(db, organization_id)
        row = await repo.get(contact_id)
        if row is None:
            raise ContactServiceError("Contact not found.", status_code=404)
        return CrmContactRead.model_validate(row)

    async def create_contact(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmContactCreate,
    ) -> CrmContactRead:
        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            await quota_service.assert_crm_contacts_quota(db, organization_id)
        except QuotaExceeded as exc:
            raise ContactServiceError(exc.detail, status_code=402) from exc

        if payload.account_id is not None:
            accounts = self._accounts(db, organization_id)
            if await accounts.get(payload.account_id) is None:
                raise ContactServiceError("Account not found in this organization.", status_code=404)

        repo = self._contacts(db, organization_id)
        entity = CrmContact(
            organization_id=organization_id,
            account_id=payload.account_id,
            first_name=payload.first_name or "",
            last_name=payload.last_name or "",
            phone=payload.phone,
            email=payload.email,
            source=payload.source,
            linked_client_id=payload.linked_client_id,
            custom_fields=dict(payload.custom_fields or {}),
            avatar_url=payload.avatar_url,
        )
        await repo.add(entity)
        result = CrmContactRead.model_validate(entity)
        try:
            from app.services.crm.webhook_dispatcher_service import notify_partner_webhooks

            await notify_partner_webhooks(
                db,
                organization_id,
                "contact.created",
                result.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.warning(
                "CRM.webhook_notify_skipped | action=create contact_id={contact_id} error={error}",
                contact_id=result.id,
                error=str(exc),
            )
        return result

    async def update_contact(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        payload: CrmContactUpdate,
    ) -> CrmContactRead:
        repo = self._contacts(db, organization_id)
        entity = await repo.get(contact_id)
        if entity is None:
            raise ContactServiceError("Contact not found.", status_code=404)

        data = payload.model_dump(exclude_unset=True)
        if "account_id" in data and data["account_id"] is not None:
            accounts = self._accounts(db, organization_id)
            if await accounts.get(data["account_id"]) is None:
                raise ContactServiceError("Account not found in this organization.", status_code=404)

        for key, value in data.items():
            setattr(entity, key, value)
        await db.flush()
        return CrmContactRead.model_validate(entity)

    async def delete_contact(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> None:
        repo = self._contacts(db, organization_id)
        entity = await repo.get(contact_id)
        if entity is None:
            raise ContactServiceError("Contact not found.", status_code=404)
        await repo.delete(entity)

    async def get_or_create_from_client(
        self,
        db: AsyncSession,
        client_id: uuid.UUID,
    ) -> CrmContact:
        """
        Lazy 1:1 bridge: inbox ``Client`` → ``CrmContact``.

        ``Client`` has no ``organization_id``; tenant is resolved via
        ``Client.bot.organization_id`` (joinedload).
        """
        stmt = (
            select(Client)
            .where(Client.id == client_id)
            .options(joinedload(Client.bot))
        )
        result = await db.execute(stmt)
        client = result.scalar_one_or_none()
        if client is None:
            raise ContactServiceError("Client not found.", status_code=404)

        bot: Bot | None = client.bot
        if bot is None:
            logger.warning(
                "CRM.capture_skip_no_bot | client_id={client_id}",
                client_id=client_id,
            )
            raise ContactServiceError("Client has no bot.", status_code=400)

        organization_id = bot.organization_id
        if organization_id is None:
            logger.warning(
                "CRM.capture_skip_no_org | client_id={client_id} bot_id={bot_id}",
                client_id=client_id,
                bot_id=bot.id,
            )
            raise ContactServiceError(
                "Bot is not bound to an organization; cannot create CRM contact.",
                status_code=400,
            )

        repo = self._contacts(db, organization_id)
        existing = await repo.get_by_linked_client_id(client.id)
        if existing is not None:
            return existing

        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            await quota_service.assert_crm_contacts_quota(db, organization_id)
        except QuotaExceeded as exc:
            # Soft-fail for Celery auto-capture: do not raise uncaught so the
            # task does not retry indefinitely when the plan is exhausted.
            logger.warning(
                "CRM.capture_quota_exceeded | client_id={client_id} "
                "organization_id={organization_id} code={code} detail={detail}",
                client_id=client.id,
                organization_id=organization_id,
                code=exc.code,
                detail=exc.detail,
            )
            raise ContactServiceError(exc.detail, status_code=402) from exc

        platform = bot.platform_type
        source = platform.value if hasattr(platform, "value") else str(platform)

        contact = CrmContact(
            organization_id=organization_id,
            linked_client_id=client.id,
            first_name=(client.first_name or "").strip() or (client.username or "").strip() or "",
            last_name="",
            source=source.lower() if source else None,
            custom_fields={},
        )
        await repo.add(contact)
        logger.info(
            "CRM.contact_captured | contact_id={contact_id} client_id={client_id} "
            "organization_id={organization_id} source={source}",
            contact_id=contact.id,
            client_id=client.id,
            organization_id=organization_id,
            source=contact.source,
        )
        try:
            from app.services.crm.webhook_dispatcher_service import notify_partner_webhooks
            from app.schemas.crm.accounts_contacts import CrmContactRead

            await notify_partner_webhooks(
                db,
                organization_id,
                "contact.created",
                CrmContactRead.model_validate(contact).model_dump(mode="json"),
            )
        except Exception as exc:
            logger.warning(
                "CRM.webhook_notify_skipped | action=capture contact_id={contact_id} error={error}",
                contact_id=contact.id,
                error=str(exc),
            )
        return contact


contact_service = ContactService()
