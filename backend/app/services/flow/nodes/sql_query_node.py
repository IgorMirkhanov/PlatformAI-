"""SQL query node for tenant-managed external databases.

Security guarantees:
  - only single-statement SELECT / WITH ... SELECT queries are allowed
  - template placeholders are compiled into SQLAlchemy bind params
  - connection strings may be stored encrypted at rest
  - preferred path: resolve ``connection_id`` from org secure storage
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.crypto import decrypt_sensitive
from app.services.flow.engine import FlowEngineError
from app.services.flow.nodes.base import BaseNodeHandler, NodeExecutionContext, NodeHandlerResult

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_COMMENT_RE = re.compile(r"(--[^\r\n]*|/\*.*?\*/)", re.DOTALL)
_DANGEROUS_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|merge|grant|revoke)\b",
    re.IGNORECASE,
)


async def _resolve_connection_string(ctx: NodeExecutionContext) -> str:
    """Resolve DSN from connection_id (preferred) or inline/env fallbacks."""
    connection_id_raw = ctx.data.get("connection_id")
    if connection_id_raw:
        if ctx.db is None or ctx.organization_id is None:
            raise FlowEngineError(
                "sql_query connection_id lookup requires db + organization_id."
            )
        try:
            connection_id = uuid.UUID(str(connection_id_raw))
        except (TypeError, ValueError) as exc:
            raise FlowEngineError("Invalid connection_id for sql_query node.") from exc

        from app.services.integrations.db_connection_service import (
            DbConnectionServiceError,
            db_connection_service,
        )

        try:
            return await db_connection_service.resolve_connection_string(
                ctx.db,
                ctx.organization_id,
                connection_id,
            )
        except DbConnectionServiceError as exc:
            raise FlowEngineError(exc.message) from exc

    raw = (
        ctx.data.get("connection_string_encrypted")
        or ctx.data.get("connection_string")
        or os.getenv("SQL_QUERY_CONNECTION_STRING")
        or ""
    )
    value = decrypt_sensitive(str(raw or "")).strip()
    if not value:
        raise FlowEngineError(
            "sql_query node requires connection_id, a tenant connection string, "
            "or SQL_QUERY_CONNECTION_STRING."
        )
    return value


def _sanitize_sql_for_validation(query: str) -> str:
    query = _COMMENT_RE.sub(" ", query)
    query = query.strip()
    if query.endswith(";"):
        query = query[:-1].rstrip()
    return query


def _validate_select_only(query: str) -> None:
    normalized = _sanitize_sql_for_validation(query)
    lowered = normalized.lower()

    if ";" in normalized:
        raise FlowEngineError("Only a single SELECT statement is allowed in sql_query nodes.")

    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise FlowEngineError("sql_query nodes allow only SELECT queries.")

    if _DANGEROUS_SQL_RE.search(normalized):
        raise FlowEngineError("Dangerous SQL command blocked. Only read-only SELECT is allowed.")


def _lookup_session_variable(variables: dict[str, Any], expression: str) -> Any:
    key = expression.strip()
    if key.startswith("session.variables."):
        key = key.removeprefix("session.variables.")
    elif key.startswith("variables."):
        key = key.removeprefix("variables.")
    return variables.get(key)


def _compile_parameterized_query(template: str, variables: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}

    def _replace(match: re.Match[str]) -> str:
        name = f"p{len(params)}"
        params[name] = _lookup_session_variable(variables, match.group(1))
        return f":{name}"

    query = _PLACEHOLDER_RE.sub(_replace, template)
    return query, params


def _normalize_driver(connection_string: str) -> str:
    lowered = connection_string.lower()
    if lowered.startswith("postgres://"):
        return "postgresql+psycopg://" + connection_string[len("postgres://") :]
    if lowered.startswith("postgresql://"):
        return "postgresql+psycopg://" + connection_string[len("postgresql://") :]
    if lowered.startswith("mysql://"):
        return "mysql+pymysql://" + connection_string[len("mysql://") :]
    return connection_string


def _build_engine(connection_string: str) -> Engine:
    return create_engine(
        _normalize_driver(connection_string),
        pool_pre_ping=True,
        poolclass=NullPool,
    )


def _run_query(connection_string: str, sql: str, params: dict[str, Any], max_rows: int) -> list[dict[str, Any]]:
    engine = _build_engine(connection_string)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            rows = result.mappings().fetchmany(max_rows)
            return [dict(row) for row in rows]
    finally:
        engine.dispose()


class SqlQueryNodeHandler(BaseNodeHandler):
    """Execute a read-only external SQL query and store the result in session vars."""

    node_types = ("sql_query",)

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        query_template = str(ctx.data.get("query") or ctx.data.get("sql") or "").strip()
        result_variable = str(ctx.data.get("result_variable") or "sql_result").strip() or "sql_result"
        max_rows = max(1, min(int(ctx.data.get("max_rows") or 50), 500))

        if not query_template:
            raise FlowEngineError("sql_query node requires a SQL query.")

        sql, params = _compile_parameterized_query(query_template, ctx.variables)
        _validate_select_only(sql)
        connection_string = await _resolve_connection_string(ctx)

        try:
            rows = await asyncio.to_thread(_run_query, connection_string, sql, params, max_rows)
        except SQLAlchemyError as exc:
            logger.warning(
                "Flow.SQLQuery.error | session={sid} error={error}",
                sid=ctx.session.session_id,
                error=str(exc),
            )
            raise FlowEngineError(f"SQL query failed: {exc}") from exc

        ctx.variables[result_variable] = rows
        ctx.variables["sql_result"] = rows

        return NodeHandlerResult(
            event="sql_query",
            output={
                "result_variable": result_variable,
                "row_count": len(rows),
                "max_rows": max_rows,
                "connection_id": ctx.data.get("connection_id"),
            },
        )
