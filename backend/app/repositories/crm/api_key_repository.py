"""CRM API key repository."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.api_key import CrmApiKey
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class ApiKeyRepository(BaseCrmRepository[CrmApiKey]):
    model = CrmApiKey

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmApiKey]:
        stmt = (
            self._base_query()
            .order_by(CrmApiKey.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_all(self) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(CrmApiKey).where(
            CrmApiKey.organization_id == self.organization_id
        )
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def touch_last_used(self, entity: CrmApiKey) -> None:
        entity.last_used_at = datetime.now(timezone.utc)
        await self.session.flush()


async def get_active_api_key_by_hash(
    session: AsyncSession,
    key_hash: str,
) -> CrmApiKey | None:
    """
    Auth bootstrap lookup — org is unknown until the key is resolved.

    Still filters ``is_active``; tenant isolation for subsequent CRM calls uses
    ``organization_id`` from the returned row via BaseCrmRepository.
    """
    stmt = select(CrmApiKey).where(
        CrmApiKey.key_hash == key_hash,
        CrmApiKey.is_active.is_(True),
    )
    return await session.scalar(stmt)


def api_key_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> ApiKeyRepository:
    return ApiKeyRepository(session, organization_id=organization_id)
