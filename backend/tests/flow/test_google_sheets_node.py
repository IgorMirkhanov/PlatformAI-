"""Unit tests for GoogleSheetsNodeHandler — all Google API calls are mocked."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.flow.engine import FlowEngineError, FlowSessionState
from app.services.flow.nodes.base import NodeExecutionContext, NodeHandlerResult
from app.services.flow.nodes.google_sheets_node import (
    GoogleSheetsNodeHandler,
    _col_letter_to_index,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_ID = str(uuid.uuid4())
ORG_ID = uuid.uuid4()


def _make_ctx(
    data: dict[str, Any],
    variables: dict[str, Any] | None = None,
) -> NodeExecutionContext:
    """Build a minimal NodeExecutionContext for testing."""
    session = FlowSessionState(
        session_id=SESSION_ID,
        flow_id="flow-1",
    )
    return NodeExecutionContext(
        node={"id": "n1", "type": "google_sheets", "data": data},
        session=session,
        variables=variables or {},
        initial_input={},
        organization_id=ORG_ID,
    )


def _mock_service(sheets_api_mock: MagicMock) -> MagicMock:
    """Return a mock that mimics googleapiclient service structure."""
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value = sheets_api_mock
    return service


# ---------------------------------------------------------------------------
# _col_letter_to_index utility
# ---------------------------------------------------------------------------

class TestColLetterToIndex:
    def test_single_a(self) -> None:
        assert _col_letter_to_index("A") == 0

    def test_single_b(self) -> None:
        assert _col_letter_to_index("B") == 1

    def test_single_z(self) -> None:
        assert _col_letter_to_index("Z") == 25

    def test_double_aa(self) -> None:
        assert _col_letter_to_index("AA") == 26

    def test_lowercase(self) -> None:
        assert _col_letter_to_index("c") == 2


# ---------------------------------------------------------------------------
# Missing spreadsheet_id raises FlowEngineError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_spreadsheet_id_raises() -> None:
    handler = GoogleSheetsNodeHandler()
    ctx = _make_ctx({"action": "append_row", "spreadsheet_id": ""})
    with pytest.raises(FlowEngineError, match="spreadsheet_id"):
        await handler.execute(ctx)


# ---------------------------------------------------------------------------
# Missing credentials raises FlowEngineError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    handler = GoogleSheetsNodeHandler()
    ctx = _make_ctx({"action": "append_row", "spreadsheet_id": "SHEET_ID"})

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        side_effect=FlowEngineError("No Google service-account credentials found."),
    ):
        with pytest.raises(FlowEngineError, match="credentials"):
            await handler.execute(ctx)


# ---------------------------------------------------------------------------
# append_row — correct values list formed from column_mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_row_uses_column_mapping() -> None:
    """Handler must build a row from session variables in column_mapping order."""
    append_mock = MagicMock()
    append_mock.execute.return_value = {
        "updates": {"updatedRange": "'Sheet1'!A2:B2"}
    }
    sheets_values = MagicMock()
    sheets_values.append.return_value = append_mock
    service = _mock_service(sheets_values)

    ctx = _make_ctx(
        data={
            "action": "append_row",
            "spreadsheet_id": "SHEET_ID",
            "sheet_name": "Sheet1",
            "column_mapping": {"A": "user_name", "B": "user_email"},
        },
        variables={"user_name": "Alice", "user_email": "alice@example.com"},
    )

    handler = GoogleSheetsNodeHandler()
    fake_creds = MagicMock()

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=fake_creds,
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=service,
    ):
        result = await handler.execute(ctx)

    assert isinstance(result, NodeHandlerResult)
    assert result.event == "google_sheets_append"
    assert result.output["action"] == "append_row"
    assert result.output["updated_range"] == "'Sheet1'!A2:B2"

    # Verify the correct row was sent to the API.
    call_kwargs = sheets_values.append.call_args
    body_sent = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
    assert body_sent["values"] == [["Alice", "alice@example.com"]]


# ---------------------------------------------------------------------------
# append_row — fallback: no column_mapping → all variables appended
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_row_fallback_all_variables() -> None:
    append_mock = MagicMock()
    append_mock.execute.return_value = {"updates": {"updatedRange": "'Sheet1'!A5:C5"}}
    sheets_values = MagicMock()
    sheets_values.append.return_value = append_mock
    service = _mock_service(sheets_values)

    ctx = _make_ctx(
        data={
            "action": "append_row",
            "spreadsheet_id": "SHEET_ID",
            "sheet_name": "Sheet1",
        },
        variables={"x": 1, "y": 2, "z": 3},
    )

    handler = GoogleSheetsNodeHandler()

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=MagicMock(),
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=service,
    ):
        result = await handler.execute(ctx)

    assert result.event == "google_sheets_append"
    assert result.output["row_length"] == 3


# ---------------------------------------------------------------------------
# read_row — found match → fills session variables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_row_found_fills_variables() -> None:
    get_mock = MagicMock()
    get_mock.execute.return_value = {
        "values": [
            ["phone", "name", "city"],
            ["+79001234567", "Bob", "Moscow"],
            ["+79009999999", "Eve", "Saint Petersburg"],
        ]
    }
    sheets_values = MagicMock()
    sheets_values.get.return_value = get_mock
    service = _mock_service(sheets_values)

    ctx = _make_ctx(
        data={
            "action": "read_row",
            "spreadsheet_id": "SHEET_ID",
            "sheet_name": "Sheet1",
            "filter_column": "A",
            "filter_value": "+79001234567",
            "column_mapping": {"name": "client_name", "city": "client_city"},
            "result_variable": "sheet_result",
        },
        variables={},
    )

    handler = GoogleSheetsNodeHandler()

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=MagicMock(),
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=service,
    ):
        result = await handler.execute(ctx)

    assert result.event == "google_sheets_read"
    assert result.output["found"] is True
    assert ctx.variables["sheet_result"] == {
        "phone": "+79001234567",
        "name": "Bob",
        "city": "Moscow",
    }
    # Column mapping must write into individual session variables.
    assert ctx.variables["client_name"] == "Bob"
    assert ctx.variables["client_city"] == "Moscow"


# ---------------------------------------------------------------------------
# read_row — no match → result_variable set to None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_row_not_found_sets_none() -> None:
    get_mock = MagicMock()
    get_mock.execute.return_value = {
        "values": [
            ["phone", "name"],
            ["+79001111111", "Alice"],
        ]
    }
    sheets_values = MagicMock()
    sheets_values.get.return_value = get_mock
    service = _mock_service(sheets_values)

    ctx = _make_ctx(
        data={
            "action": "read_row",
            "spreadsheet_id": "SHEET_ID",
            "sheet_name": "Sheet1",
            "filter_column": "A",
            "filter_value": "+00000000000",
            "result_variable": "sheet_result",
        },
        variables={},
    )

    handler = GoogleSheetsNodeHandler()

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=MagicMock(),
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=service,
    ):
        result = await handler.execute(ctx)

    assert result.output["found"] is False
    assert ctx.variables["sheet_result"] is None


# ---------------------------------------------------------------------------
# read_row — empty sheet → not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_row_empty_sheet() -> None:
    get_mock = MagicMock()
    get_mock.execute.return_value = {"values": []}
    sheets_values = MagicMock()
    sheets_values.get.return_value = get_mock
    service = _mock_service(sheets_values)

    ctx = _make_ctx(
        data={
            "action": "read_row",
            "spreadsheet_id": "SHEET_ID",
            "sheet_name": "Sheet1",
            "filter_column": "A",
            "filter_value": "anything",
        },
        variables={},
    )

    handler = GoogleSheetsNodeHandler()

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=MagicMock(),
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=service,
    ):
        result = await handler.execute(ctx)

    assert result.output["found"] is False


# ---------------------------------------------------------------------------
# Unknown action raises FlowEngineError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action_raises() -> None:
    handler = GoogleSheetsNodeHandler()
    ctx = _make_ctx(
        data={"action": "delete_row", "spreadsheet_id": "SHEET_ID"},
    )

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=MagicMock(),
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=MagicMock(),
    ):
        with pytest.raises(FlowEngineError, match="Unknown google_sheets action"):
            await handler.execute(ctx)


# ---------------------------------------------------------------------------
# API error is wrapped into FlowEngineError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_error_wrapped_as_flow_engine_error() -> None:
    sheets_values = MagicMock()
    append_mock = MagicMock()
    append_mock.execute.side_effect = Exception("403 forbidden")
    sheets_values.append.return_value = append_mock
    service = _mock_service(sheets_values)

    ctx = _make_ctx(
        data={"action": "append_row", "spreadsheet_id": "SHEET_ID"},
        variables={"x": "1"},
    )

    handler = GoogleSheetsNodeHandler()

    with patch(
        "app.services.flow.nodes.google_sheets_node._build_credentials",
        return_value=MagicMock(),
    ), patch(
        "app.services.flow.nodes.google_sheets_node._build_service",
        return_value=service,
    ):
        with pytest.raises(FlowEngineError, match="Google Sheets API error"):
            await handler.execute(ctx)


# ---------------------------------------------------------------------------
# Handler is registered in the default registry
# ---------------------------------------------------------------------------

def test_google_sheets_registered_in_default_registry() -> None:
    from app.services.flow.nodes.base import build_default_node_registry

    registry = build_default_node_registry()
    handler = registry.get("google_sheets")
    assert handler is not None
    assert isinstance(handler, GoogleSheetsNodeHandler)
