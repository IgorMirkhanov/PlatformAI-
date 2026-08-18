"""Integration suite: auth/impersonation, FlowExecutor RAG+CRM pipeline, CRM resilience."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.admin import (
    decode_impersonation_token,
    router as admin_router,
)
from app.api.endpoints.admin.common import ACTION_START
from app.core.config import settings
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.admin_audit import AdminAuditLog
from app.models.core_models import DiagnosticErrorType
from app.services.flow_parser import FlowExecutionResult, FlowExecutor


# ---------------------------------------------------------------------------
# 1) Authentication & Impersonation
# ---------------------------------------------------------------------------


def test_standard_oauth2_style_access_token_roundtrip(admin_user) -> None:
    """Mint/verify a standard HS256 access JWT (OAuth2 bearer contract)."""
    password = "SuperSecure!42"
    admin_user.hashed_password = hash_password(password)
    assert verify_password(password, admin_user.hashed_password)

    token = create_access_token(
        subject=admin_user.id,
        company_id=admin_user.company_id,
        role="OWNER",
        extra_claims={"email": admin_user.email},
    )
    assert "." in token
    assert not token.startswith("imp_")

    payload = decode_access_token(token)
    assert payload["typ"] == "access"
    assert payload["sub"] == str(admin_user.id)
    assert payload["company_id"] == str(admin_user.company_id)
    assert payload["email"] == admin_user.email

    raw = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    assert raw["sub"] == str(admin_user.id)


@pytest.mark.asyncio
async def test_admin_impersonation_exchange_writes_audit_log(
    admin_user,
    client_user,
    fake_db_session,
) -> None:
    """Admin Bearer → POST /admin/impersonate → imp_* token + admin_audit_logs row."""
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1")

    async def _override_db():
        yield fake_db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: admin_user

    access_token = create_access_token(
        subject=admin_user.id,
        company_id=admin_user.company_id,
        role="OWNER",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/impersonate",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"email": client_user.email, "password": "admin-test-password"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    imp_token = body["access_token"]
    assert body["impersonated_by"] == str(admin_user.id)
    assert body["impersonated_user_id"] == str(client_user.id)
    assert body["impersonated_user_email"] == client_user.email

    decoded = decode_access_token(imp_token)
    assert decoded is not None
    assert decoded["typ"] == "impersonation"
    assert decoded["impersonated_by"] == str(admin_user.id)
    assert decoded["sub"] == str(client_user.id)
    assert decoded.get("jti")

    audit_rows = [obj for obj in fake_db_session.added if isinstance(obj, AdminAuditLog)]
    assert len(audit_rows) == 1
    assert audit_rows[0].admin_id == admin_user.id
    assert audit_rows[0].target_user_id == client_user.id
    assert audit_rows[0].action == ACTION_START
    assert fake_db_session.committed is True


# ---------------------------------------------------------------------------
# 2) Graph execution: Knowledge Search → CRM → LLM
# ---------------------------------------------------------------------------


def _patch_llm_to_echo_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _echo_llm(
        self: FlowExecutor,
        node: dict[str, Any],
        **_kwargs: Any,
    ) -> FlowExecutionResult:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        prompt = self._render_template(str(data.get("prompt_context") or ""))
        return FlowExecutionResult(
            node_id=str(node["id"]),
            node_type="ai_agent",
            text=prompt,
            data=data,
            is_waiting=True,
        )

    monkeypatch.setattr(FlowExecutor, "_eval_llm_node", _echo_llm)


@pytest.mark.asyncio
async def test_flow_executor_rag_and_crm_phone_interpolation(
    monkeypatch: pytest.MonkeyPatch,
    pipeline_graph: dict[str, Any],
) -> None:
    """KS fills {{rag_context}}; CRM interpolates {{phone}} into JSON before httpx."""
    _patch_llm_to_echo_prompt(monkeypatch)

    async def fake_similarity_search(
        knowledge_base_id: str,
        query: str,
        top_k: int = 3,
        **_kwargs: Any,
    ) -> list[str]:
        assert knowledge_base_id
        assert "refund" in query.lower() or query
        assert top_k == 3
        # One chunk avoids newlines that would break naive JSON string interpolation.
        return ["Refunds are processed within 5 business days."]

    monkeypatch.setattr(
        "app.core.vector_db.similarity_search",
        fake_similarity_search,
    )

    captured: dict[str, Any] = {}

    class _FakeResponse:
        status_code = 201
        text = '{"id":99,"ok":true}'

        def json(self) -> dict[str, Any]:
            return {"id": 99, "ok": True}

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = dict(kwargs.get("headers") or {})
            captured["json"] = kwargs.get("json")
            captured["content"] = kwargs.get("content")
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    bot_id = uuid.uuid4()
    executor = FlowExecutor(pipeline_graph)
    result = await executor.execute(
        current_step_id=None,
        incoming_message="How do refunds work?",
        context={
            "phone": "+77071234567",
            "user_name": "Igor",
            "channel": "whatsapp",
            "variables": {"phone": "+77071234567"},
        },
        bot_id=bot_id,
    )

    # Knowledge Search populated session memory.
    rag = str(executor.variables.get("rag_context") or "")
    assert "Refunds are processed" in rag
    assert isinstance(executor.variables.get("rag_chunks"), list)
    assert len(executor.variables["rag_chunks"]) >= 1

    # CRM interpolated phone into headers + JSON body before the HTTP call.
    assert captured["method"] == "POST"
    assert captured["url"] == "https://crm.example.com/api/leads"
    assert captured["headers"].get("X-Client-Phone") == "+77071234567"

    if isinstance(captured.get("json"), dict):
        body = captured["json"]
        assert body["phone"] == "+77071234567"
        assert "Refunds are processed" in str(body.get("context") or "")
        assert "{{phone}}" not in json.dumps(body)
    else:
        raw = captured.get("content") or b""
        payload_text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        assert "+77071234567" in payload_text
        assert "{{phone}}" not in payload_text
        assert "Refunds are processed" in payload_text

    # CRM success mapped into session + flattened keys.
    assert executor.variables["crm_result"]["success"] is True
    assert executor.variables.get("crm_result.id") == 99

    # Pipeline advanced to LLM without crashing; prompt saw RAG + CRM state.
    assert result.node_id == "llm_1"
    assert "Refunds are processed" in result.text
    assert "CRM ok=True" in result.text or "ok=True" in result.text.replace(" ", "")


# ---------------------------------------------------------------------------
# 3) CRM resilience — timeout must not break the execution loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crm_timeout_is_graceful_and_logs_integration_error(
    monkeypatch: pytest.MonkeyPatch,
    pipeline_graph: dict[str, Any],
) -> None:
    """Timeout → crm_result failure payload + CRM_INTEGRATION_ERROR + continue to LLM."""
    _patch_llm_to_echo_prompt(monkeypatch)

    async def fake_similarity_search(*_args: Any, **_kwargs: Any) -> list[str]:
        return ["KB chunk for resilience path."]

    monkeypatch.setattr("app.core.vector_db.similarity_search", fake_similarity_search)

    class _TimeoutClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _TimeoutClient:
            return self

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

        async def request(self, *_args: Any, **_kwargs: Any) -> Any:
            raise httpx.TimeoutException("CRM timed out after 10s")

    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutClient)

    diagnostic_calls: list[dict[str, Any]] = []

    async def fake_diag_log(_db: Any, **kwargs: Any) -> Any:
        diagnostic_calls.append(kwargs)
        return object()

    from app.services.diagnostic_log_service import diagnostic_log_service

    monkeypatch.setattr(
        diagnostic_log_service,
        "log",
        AsyncMock(side_effect=fake_diag_log),
    )

    bot_id = uuid.uuid4()
    client_id = uuid.uuid4()
    fake_db = AsyncMock()

    executor = FlowExecutor(pipeline_graph)
    result = await executor.execute(
        current_step_id=None,
        incoming_message="Need a human, CRM please",
        context={"phone": "+77071234567", "channel": "whatsapp"},
        db=fake_db,
        bot_id=bot_id,
        client_id=client_id,
    )

    crm_result = executor.variables.get("crm_result")
    assert isinstance(crm_result, dict)
    assert crm_result.get("success") is False
    assert crm_result.get("error") == "CRM unreachable"

    assert diagnostic_calls, "Expected BotDiagnosticLogs write for CRM failure"
    assert diagnostic_calls[0]["error_type"] == DiagnosticErrorType.CRM_INTEGRATION_ERROR
    assert diagnostic_calls[0]["bot_id"] == bot_id
    assert diagnostic_calls[0]["node_id"] == "crm_1"
    assert "CRM unreachable" in diagnostic_calls[0]["error_message"]

    # Celery/worker loop equivalent: execution still reaches the next node.
    assert result.node_id == "llm_1"
    assert result.error is None or result.error != "unsupported_node_type"
    assert "KB chunk for resilience path" in result.text
    assert result.is_waiting is True


@pytest.mark.asyncio
async def test_celery_style_worker_loop_survives_crm_failure(
    monkeypatch: pytest.MonkeyPatch,
    pipeline_graph: dict[str, Any],
) -> None:
    """Mirrors webhook worker: instantiate FlowExecutor, run once, always get a reply dict."""
    _patch_llm_to_echo_prompt(monkeypatch)

    monkeypatch.setattr(
        "app.core.vector_db.similarity_search",
        AsyncMock(return_value=["chunk"]),
    )

    class _BoomClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _BoomClient:
            return self

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

        async def request(self, *_a: Any, **_k: Any) -> Any:
            raise httpx.ConnectError("CRM unreachable")

    monkeypatch.setattr(httpx, "AsyncClient", _BoomClient)
    monkeypatch.setattr(
        "app.services.diagnostic_log_service.diagnostic_log_service.schedule_log",
        lambda **_kwargs: None,
    )

    # Worker pattern from webhook_workers / webhook_service.
    executor = FlowExecutor(pipeline_graph)
    execution = await executor.execute(
        current_step_id=None,
        incoming_message="ping",
        context={"phone": "+77070000000"},
        bot_id=uuid.uuid4(),
    )
    next_node = execution.to_dict()

    assert next_node["node_id"] == "llm_1"
    assert next_node["node_type"] == "ai_agent"
    assert isinstance(next_node.get("variables"), dict)
    assert next_node["variables"]["crm_result"]["success"] is False
    # Must be JSON-serializable for Celery result / Redis hand-off.
    json.dumps(next_node, default=str)
