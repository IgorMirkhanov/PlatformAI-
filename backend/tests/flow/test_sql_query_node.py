"""Unit tests for SqlQueryNodeHandler + secure DB connection resolution."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.crypto import encrypt_sensitive, reset_field_encryptor
from app.services.flow.engine import FlowEngineError, FlowSessionState
from app.services.flow.nodes.base import NodeExecutionContext
from app.services.flow.nodes.sql_query_node import (
    SqlQueryNodeHandler,
    _compile_parameterized_query,
    _validate_select_only,
)
from app.services.integrations.db_connection_service import DbConnectionService
from app.schemas.integrations.db_connections import DbConnectionCreate

SESSION_ID = str(uuid.uuid4())
ORG_ID = uuid.uuid4()


def _make_ctx(
    data: dict[str, Any],
    variables: dict[str, Any] | None = None,
    *,
    db: Any | None = None,
) -> NodeExecutionContext:
    session = FlowSessionState(session_id=SESSION_ID, flow_id="flow-1")
    return NodeExecutionContext(
        node={"id": "sql-1", "type": "sql_query", "data": data},
        session=session,
        variables=variables or {},
        initial_input={},
        organization_id=ORG_ID,
        db=db,
    )


def test_compile_parameterized_query_rewrites_placeholders() -> None:
    sql, params = _compile_parameterized_query(
        "SELECT * FROM products WHERE sku = {{ session.variables.user_sku }} AND tenant = {{tenant}}",
        {"user_sku": "SKU-1", "tenant": "acme"},
    )
    assert sql == "SELECT * FROM products WHERE sku = :p0 AND tenant = :p1"
    assert params == {"p0": "SKU-1", "p1": "acme"}


@pytest.mark.parametrize(
    "query",
    [
        "UPDATE products SET price = 1",
        "DELETE FROM products",
        "DROP TABLE products",
        "SELECT * FROM x; DELETE FROM y",
    ],
)
def test_dangerous_queries_are_rejected(query: str) -> None:
    with pytest.raises(FlowEngineError):
        _validate_select_only(query)


@pytest.mark.asyncio
async def test_safe_select_query_executes_with_parameterization() -> None:
    handler = SqlQueryNodeHandler()
    ctx = _make_ctx(
        {
            "connection_string": "postgresql://user:pass@db.example.com:5432/catalog",
            "query": "SELECT sku, title FROM products WHERE sku = {{ session.variables.user_sku }}",
            "result_variable": "sql_result",
            "max_rows": 10,
        },
        {"user_sku": "SKU-1"},
    )

    with patch(
        "app.services.flow.nodes.sql_query_node._run_query",
        return_value=[{"sku": "SKU-1", "title": "Widget"}],
    ) as run_query:
        result = await handler.execute(ctx)

    assert result.event == "sql_query"
    assert result.output["row_count"] == 1
    assert ctx.variables["sql_result"] == [{"sku": "SKU-1", "title": "Widget"}]

    args = run_query.call_args.args
    assert args[0] == "postgresql://user:pass@db.example.com:5432/catalog"
    assert args[1] == "SELECT sku, title FROM products WHERE sku = :p0"
    assert args[2] == {"p0": "SKU-1"}
    assert args[3] == 10


@pytest.mark.asyncio
async def test_connection_id_is_resolved_from_secure_storage() -> None:
    connection_id = uuid.uuid4()
    handler = SqlQueryNodeHandler()
    ctx = _make_ctx(
        {
            "connection_id": str(connection_id),
            "query": "SELECT 1 AS ok",
        },
        db=MagicMock(),
    )

    with patch(
        "app.services.integrations.db_connection_service.db_connection_service.resolve_connection_string",
        new=AsyncMock(return_value="postgresql://user:secret@db/catalog"),
    ) as resolve, patch(
        "app.services.flow.nodes.sql_query_node._run_query",
        return_value=[{"ok": 1}],
    ) as run_query:
        result = await handler.execute(ctx)

    resolve.assert_awaited_once()
    assert run_query.call_args.args[0] == "postgresql://user:secret@db/catalog"
    assert result.output["connection_id"] == str(connection_id)
    assert ctx.variables["sql_result"] == [{"ok": 1}]


@pytest.mark.asyncio
async def test_connection_id_without_db_raises() -> None:
    handler = SqlQueryNodeHandler()
    ctx = _make_ctx(
        {
            "connection_id": str(uuid.uuid4()),
            "query": "SELECT 1",
        },
        db=None,
    )
    with pytest.raises(FlowEngineError, match="db \\+ organization_id"):
        await handler.execute(ctx)


@pytest.mark.asyncio
async def test_create_connection_encrypts_dsn_and_hides_plaintext() -> None:
    reset_field_encryptor()
    service = DbConnectionService()
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    captured: dict[str, Any] = {}

    def _capture(entity: Any) -> None:
        captured["entity"] = entity

    db.add.side_effect = _capture

    async def _refresh(entity: Any) -> None:
        entity.id = uuid.uuid4()
        entity.organization_id = ORG_ID
        entity.created_by_id = None
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        entity.created_at = now
        entity.updated_at = now

    db.refresh.side_effect = _refresh

    plaintext = "postgresql://admin:SuperSecret@db.internal:5432/prod"
    out = await service.create_connection(
        db,
        ORG_ID,
        DbConnectionCreate(
            name="Production Read Replica",
            db_type="postgresql",
            connection_string=plaintext,
        ),
    )

    entity = captured["entity"]
    assert plaintext not in entity.connection_string_encrypted
    assert "SuperSecret" not in entity.connection_string_encrypted
    assert out.model_dump().get("connection_string") is None
    assert "connection_string_encrypted" not in out.model_dump()
    assert out.name == "Production Read Replica"


def test_encrypt_sensitive_roundtrip_for_connection_string() -> None:
    reset_field_encryptor()
    plaintext = "mysql://root:hunter2@127.0.0.1:3306/app"
    sealed = encrypt_sensitive(plaintext)
    assert plaintext not in sealed
    from app.core.crypto import decrypt_sensitive

    assert decrypt_sensitive(sealed) == plaintext


@pytest.mark.asyncio
async def test_sql_handler_registered_in_default_registry() -> None:
    from app.services.flow.nodes.base import build_default_node_registry

    registry = build_default_node_registry()
    handler = registry.get("sql_query")
    assert isinstance(handler, SqlQueryNodeHandler)
