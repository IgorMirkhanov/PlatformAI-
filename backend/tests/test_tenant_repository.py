"""Unit tests — soft-delete helper used by TenantRepository."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.repositories.base import TenantRepository


class _Entity:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.organization_id = uuid.uuid4()
        self.deleted_at = None


class _Session:
    async def flush(self) -> None:
        return None

    def add(self, _obj) -> None:
        return None


class _Repo(TenantRepository[_Entity]):
    model = _Entity  # type: ignore[assignment]
    tenant_field = "organization_id"


@pytest.mark.asyncio
async def test_soft_delete_sets_timestamp():
    entity = _Entity()
    repo = _Repo(_Session(), organization_id=entity.organization_id)  # type: ignore[arg-type]
    await repo.soft_delete(entity)
    assert entity.deleted_at is not None
    assert isinstance(entity.deleted_at, datetime)


def test_tenant_context_defaults():
    repo = _Repo(SimpleNamespace(), organization_id=uuid.uuid4())  # type: ignore[arg-type]
    assert repo.include_deleted is False
    assert repo.organization_id is not None
