"""Alembic environment — async SQLAlchemy 2.0."""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

# `backend/alembic/` (revision scripts) is a PEP 420 namespace that shadows the
# PyPI `alembic` package whenever cwd/pythonpath is `backend/`. Prefer site-packages.
for _entry in list(sys.path):
    if "site-packages" in _entry.replace("\\", "/").lower():
        sys.path.insert(0, _entry)
_alembic_mod = sys.modules.get("alembic")
if _alembic_mod is not None and getattr(_alembic_mod, "__file__", None) is None:
    for _name in list(sys.modules):
        if _name == "alembic" or _name.startswith("alembic."):
            del sys.modules[_name]

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import Base

# Register all models on Base.metadata
import app.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
