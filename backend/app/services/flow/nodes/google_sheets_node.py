"""Google Sheets integration node for Flow Builder.

Supports two actions:
  - ``append_row``  — write a row to the sheet from session variables.
  - ``read_row``    — search a column for a value and return the matching
                      row into ``session.variables["sheet_result"]``.

Credentials are resolved (in priority order):
  1. ``ctx.data["credentials_json"]``  — inline JSON passed from encrypted org settings.
  2. ``GOOGLE_SERVICE_ACCOUNT_JSON`` env-var — full JSON string.
  3. ``GOOGLE_APPLICATION_CREDENTIALS`` env-var — path to a service-account file (ADC).
"""

from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

from app.services.flow.engine import FlowEngineError
from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
)

# ---------------------------------------------------------------------------
# Optional dependency guard — google-api-python-client / google-auth
# ---------------------------------------------------------------------------
try:
    import googleapiclient.discovery  # type: ignore[import-untyped]
    import googleapiclient.errors  # type: ignore[import-untyped]
    from google.oauth2 import service_account  # type: ignore[import-untyped]

    _GOOGLE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GOOGLE_AVAILABLE = False

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_credentials(ctx: NodeExecutionContext):  # type: ignore[return]
    """Return google.oauth2 Credentials from node data or environment."""
    if not _GOOGLE_AVAILABLE:
        raise FlowEngineError(
            "Google Sheets dependencies are not installed. "
            "Run: pip install google-api-python-client google-auth"
        )

    # 1. Inline credentials from node data (org-encrypted settings → decrypted at runtime)
    raw = ctx.data.get("credentials_json")
    if raw:
        info = json.loads(raw) if isinstance(raw, str) else raw
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)

    # 2. Full JSON in env-var
    env_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if env_json:
        info = json.loads(env_json)
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)

    # 3. Application Default Credentials path
    adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if adc_path:
        return service_account.Credentials.from_service_account_file(adc_path, scopes=_SCOPES)

    raise FlowEngineError(
        "No Google service-account credentials found. "
        "Provide credentials_json in node settings or set GOOGLE_SERVICE_ACCOUNT_JSON env-var."
    )


def _build_service(credentials):  # type: ignore[return, no-untyped-def]
    return googleapiclient.discovery.build(
        "sheets", "v4", credentials=credentials, cache_discovery=False
    )


def _range(sheet_name: str, column: str | None = None) -> str:
    if column:
        return f"'{sheet_name}'!{column}:{column}"
    return f"'{sheet_name}'"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class GoogleSheetsNodeHandler(BaseNodeHandler):
    """Flow node handler for Google Sheets append / read operations."""

    node_types = ("google_sheets",)

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        data = ctx.data
        action = str(data.get("action") or "append_row").strip().lower()
        spreadsheet_id = ctx.interpolate(str(data.get("spreadsheet_id") or ""))
        sheet_name = ctx.interpolate(str(data.get("sheet_name") or "Sheet1"))

        if not spreadsheet_id:
            raise FlowEngineError("google_sheets node requires spreadsheet_id.")

        credentials = _build_credentials(ctx)

        try:
            if action == "append_row":
                return await self._append_row(ctx, credentials, spreadsheet_id, sheet_name, data)
            if action == "read_row":
                return await self._read_row(ctx, credentials, spreadsheet_id, sheet_name, data)
            raise FlowEngineError(f"Unknown google_sheets action: {action!r}")
        except FlowEngineError:
            raise
        except Exception as exc:
            # Surface Google API HTTP errors and other unexpected failures.
            logger.warning(
                "Flow.GoogleSheets.error | session={sid} action={action} error={error}",
                sid=ctx.session.session_id,
                action=action,
                error=str(exc),
            )
            raise FlowEngineError(f"Google Sheets API error: {exc}") from exc

    # ------------------------------------------------------------------
    # append_row
    # ------------------------------------------------------------------

    async def _append_row(
        self,
        ctx: NodeExecutionContext,
        credentials: Any,
        spreadsheet_id: str,
        sheet_name: str,
        data: dict[str, Any],
    ) -> NodeHandlerResult:
        """Append one row.  column_mapping: {sheet_column_key: session_variable_name}."""
        column_mapping: dict[str, str] = data.get("column_mapping") or {}
        row_values: list[Any] = []

        if column_mapping:
            # Build an ordered list according to the mapping order.
            for _col_key, var_name in column_mapping.items():
                row_values.append(ctx.variables.get(var_name, ""))
        else:
            # Fallback: append all current session variables as a flat row.
            row_values = list(ctx.variables.values())

        service = _build_service(credentials)
        body = {"values": [row_values]}
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=_range(sheet_name),
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )

        updated_range = result.get("updates", {}).get("updatedRange", "")
        logger.info(
            "Flow.GoogleSheets.appended | session={sid} range={range}",
            sid=ctx.session.session_id,
            range=updated_range,
        )
        return NodeHandlerResult(
            event="google_sheets_append",
            output={
                "action": "append_row",
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "updated_range": updated_range,
                "row_length": len(row_values),
            },
        )

    # ------------------------------------------------------------------
    # read_row
    # ------------------------------------------------------------------

    async def _read_row(
        self,
        ctx: NodeExecutionContext,
        credentials: Any,
        spreadsheet_id: str,
        sheet_name: str,
        data: dict[str, Any],
    ) -> NodeHandlerResult:
        """Read rows, find first matching the filter, store result dict in session.

        data keys:
          filter_column   — A, B, C … (1-based letter, default "A")
          filter_value    — interpolated string to match (exact, case-insensitive)
          column_mapping  — {sheet_column_key: session_variable_name}
          result_variable — session variable to store the matched row dict (default "sheet_result")
        """
        filter_column = ctx.interpolate(str(data.get("filter_column") or "A"))
        filter_value = ctx.interpolate(str(data.get("filter_value") or "")).strip().lower()
        column_mapping: dict[str, str] = data.get("column_mapping") or {}
        result_variable = str(data.get("result_variable") or "sheet_result")

        service = _build_service(credentials)

        # Fetch the full sheet to allow column-key lookups.
        raw = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=_range(sheet_name),
            )
            .execute()
        )
        rows: list[list[Any]] = raw.get("values") or []

        if not rows:
            ctx.variables[result_variable] = None
            return NodeHandlerResult(
                event="google_sheets_read",
                output={
                    "action": "read_row",
                    "spreadsheet_id": spreadsheet_id,
                    "sheet_name": sheet_name,
                    "found": False,
                },
            )

        # First row is treated as a header.
        header: list[str] = [str(c) for c in rows[0]]
        data_rows = rows[1:]

        # Determine the 0-based index of the filter column.
        col_index = _col_letter_to_index(filter_column)

        matched_row: dict[str, Any] | None = None
        for row in data_rows:
            cell_value = str(row[col_index]).strip().lower() if col_index < len(row) else ""
            if cell_value == filter_value:
                matched_row = {
                    header[i]: row[i] if i < len(row) else ""
                    for i in range(len(header))
                }
                break

        # Map sheet columns → session variable names.
        if matched_row is not None and column_mapping:
            for col_key, var_name in column_mapping.items():
                ctx.variables[var_name] = matched_row.get(col_key, "")

        ctx.variables[result_variable] = matched_row

        logger.info(
            "Flow.GoogleSheets.read | session={sid} found={found}",
            sid=ctx.session.session_id,
            found=matched_row is not None,
        )
        return NodeHandlerResult(
            event="google_sheets_read",
            output={
                "action": "read_row",
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "found": matched_row is not None,
                "result_variable": result_variable,
            },
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _col_letter_to_index(col: str) -> int:
    """Convert column letter(s) A-Z / AA-ZZ to 0-based index."""
    col = col.strip().upper()
    index = 0
    for ch in col:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1
