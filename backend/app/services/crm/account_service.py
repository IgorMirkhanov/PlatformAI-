"""CRM account service — tenant-scoped CRUD."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.account import CrmAccount
from app.repositories.crm.account_repository import account_repository
from app.schemas.crm.accounts_contacts import (
    CrmAccountCreate,
    CrmAccountListResponse,
    CrmAccountRead,
    CrmAccountUpdate,
)


class AccountServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AccountService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return account_repository(db, organization_id=organization_id)

    async def list_accounts(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CrmAccountListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_filtered(q=q, limit=limit, offset=offset)
        total = await repo.count_filtered(q=q)
        return CrmAccountListResponse(
            items=[CrmAccountRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_account(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> CrmAccountRead:
        repo = self._repo(db, organization_id)
        row = await repo.get(account_id)
        if row is None:
            raise AccountServiceError("Account not found.", status_code=404)
        return CrmAccountRead.model_validate(row)

    async def create_account(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmAccountCreate,
    ) -> CrmAccountRead:
        repo = self._repo(db, organization_id)
        entity = CrmAccount(
            organization_id=organization_id,
            name=payload.name,
            industry=payload.industry,
            website=payload.website,
            custom_fields=dict(payload.custom_fields or {}),
        )
        await repo.add(entity)
        return CrmAccountRead.model_validate(entity)

    async def update_account(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        account_id: uuid.UUID,
        payload: CrmAccountUpdate,
    ) -> CrmAccountRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(account_id)
        if entity is None:
            raise AccountServiceError("Account not found.", status_code=404)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(entity, key, value)
        await db.flush()
        return CrmAccountRead.model_validate(entity)

    async def delete_account(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(account_id)
        if entity is None:
            raise AccountServiceError("Account not found.", status_code=404)
        await repo.delete(entity)


account_service = AccountService()
