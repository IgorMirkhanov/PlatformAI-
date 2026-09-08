"""Fresh-install create_all must not stall on the bots ↔ integrations FK cycle."""

from __future__ import annotations

import app.models  # noqa: F401
from app.core.database import Base
from app.models.core_models import Bot


def test_bot_integration_fks_use_alter() -> None:
    fks = [
        fk
        for fk in Bot.__table__.foreign_keys
        if fk.column.table.name == "integrations"
    ]
    assert len(fks) == 2
    assert all(fk.use_alter for fk in fks)


def test_schema_sort_places_users_before_bots() -> None:
    names = [table.name for table in Base.metadata.sorted_tables]
    assert "users" in names
    assert "bots" in names
    assert names.index("users") < names.index("bots")
