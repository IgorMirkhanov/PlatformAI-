"""Correlation IDs must appear on 4xx/5xx JSON bodies (launch checklist §2.8)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException, Request
from starlette.datastructures import URL

from main import http_exception_handler, unhandled_exception_handler
from app.services.quota_service import QuotaExceeded


def _request(cid: str = "cid-test-launch") -> MagicMock:
    request = MagicMock(spec=Request)
    request.state = SimpleNamespace(correlation_id=cid, error_occurred=False)
    request.url = URL("http://test/api/v1/quota")
    request.method = "POST"
    return request


async def test_http_exception_402_includes_correlation_id() -> None:
    request = _request()
    exc = HTTPException(
        status_code=402,
        detail={"code": "bots_limit", "message": "upgrade", "billing_url": "/billing"},
    )
    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)
    assert response.status_code == 402
    assert body["correlation_id"] == "cid-test-launch"
    assert body["detail"]["code"] == "bots_limit"
    assert response.headers.get("X-Correlation-ID") == "cid-test-launch"


async def test_unhandled_quota_exceeded_includes_correlation_id() -> None:
    request = _request("cid-quota")
    response = await unhandled_exception_handler(
        request, QuotaExceeded("messages_limit", "plan exhausted")
    )
    body = json.loads(response.body)
    assert response.status_code == 402
    assert body["correlation_id"] == "cid-quota"


async def test_unhandled_500_includes_correlation_id() -> None:
    request = _request("cid-500")
    response = await unhandled_exception_handler(request, RuntimeError("boom"))
    body = json.loads(response.body)
    assert response.status_code == 500
    assert body["correlation_id"] == "cid-500"
    assert "boom" not in str(body)
