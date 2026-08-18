"""Cross-domain ACL smoke checks for points 4–12 hardening."""

from __future__ import annotations

import inspect

from app.api.endpoints import (
    bot_knowledge,
    chat,
    chats,
    crm_integrations,
    flow_execution,
    flow_versions,
    knowledge_base,
    sandbox,
    test_chat,
    webhooks,
)
from app.api.websockets import operator_ws
from app.core.security import encrypt_credential
from app.core.config import settings


def test_sandbox_and_execute_require_bot_access() -> None:
    assert "_bot" in inspect.signature(sandbox.post_sandbox_message).parameters
    assert "_bot" in inspect.signature(test_chat.post_test_chat_message).parameters
    assert "_bot" in inspect.signature(flow_execution.execute_bot_flow).parameters
    assert "_bot" in inspect.signature(flow_versions.rollback_flow_revision).parameters


def test_crm_and_kb_require_bot_access() -> None:
    assert "_bot" in inspect.signature(crm_integrations.get_crm_status).parameters
    assert "_bot" in inspect.signature(knowledge_base.list_knowledge_base_documents).parameters
    assert "_bot" in inspect.signature(bot_knowledge.list_bot_knowledge_documents).parameters
    assert "_bot" in inspect.signature(knowledge_base.delete_knowledge_base_document).parameters


def test_inbox_endpoints_require_auth() -> None:
    assert "current_user" in inspect.signature(chats.list_active_chats).parameters
    assert "current_user" in inspect.signature(chat.intercept_dialog).parameters
    assert "current_user" in inspect.signature(chats.get_operator_context).parameters


def test_simulate_webhook_requires_auth() -> None:
    assert "current_user" in inspect.signature(webhooks.simulate_webhook).parameters
    assert "current_user" in inspect.signature(webhooks.simulate_webhook_sync).parameters


def test_operator_ws_prefers_jwt_auth() -> None:
    source = inspect.getsource(operator_ws.operator_websocket)
    assert "authenticate_websocket_user" in source


def test_encrypt_credential_never_plain_in_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    # If crypto keys are missing this should raise rather than emit plain:
    try:
        sealed = encrypt_credential("test-secret-token")
        assert not sealed.startswith("plain:")
    except RuntimeError:
        pass
