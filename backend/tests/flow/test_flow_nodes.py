"""Step 3.2 — Flow node handlers: condition, LLM, API SSRF, CRM."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.flow.engine import FlowEngineError, FlowExecutionEngine, FlowSessionManager
from app.services.flow.executor import execute_flow
from app.services.flow.nodes.api_request import ApiRequestNodeHandler
from app.services.flow.nodes.base import build_default_node_registry
from app.services.flow.nodes.condition import ConditionNodeHandler, evaluate_condition
from app.services.flow.nodes.crm_action import CrmActionNodeHandler
from app.services.flow.nodes.llm_node import LLMNodeHandler
from app.services.llm.base import LLMResponse


class InMemoryAsyncRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


def test_evaluate_condition_operators() -> None:
    assert evaluate_condition(left="vip", operator="equals", right="vip")
    assert evaluate_condition(left="hello world", operator="contains", right="world")
    assert evaluate_condition(left=10, operator="greater_than", right=3)
    assert not evaluate_condition(left=2, operator="greater_than", right=9)


@pytest.mark.asyncio
async def test_condition_node_branches_true_false() -> None:
    redis = InMemoryAsyncRedis()
    manager = FlowSessionManager(redis_client=redis)
    registry = build_default_node_registry()

    graph = {
        "nodes": [
            {"id": "trigger", "type": "trigger", "data": {}},
            {
                "id": "cond",
                "type": "condition",
                "data": {"variable": "tier", "operator": "equals", "value": "vip"},
            },
            {"id": "vip_msg", "type": "message", "data": {"text": "VIP path"}},
            {"id": "std_msg", "type": "message", "data": {"text": "Standard path"}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e0", "source": "trigger", "target": "cond"},
            {
                "id": "et",
                "source": "cond",
                "target": "vip_msg",
                "sourceHandle": "true",
                "data": {"branch": "true"},
            },
            {
                "id": "ef",
                "source": "cond",
                "target": "std_msg",
                "sourceHandle": "false",
                "data": {"branch": "false"},
            },
            {"id": "e1", "source": "vip_msg", "target": "end"},
            {"id": "e2", "source": "std_msg", "target": "end"},
        ],
    }

    vip = await execute_flow(
        None,
        "flow-cond",
        "sess-vip",
        {"tier": "vip", "message": "hi", "sender_id": "u1"},
        graph=graph,
        session_manager=manager,
        node_registry=registry,
    )
    assert "vip_msg" in vip.path
    assert "std_msg" not in vip.path
    assert vip.variables["branch"] == "true"

    std = await execute_flow(
        None,
        "flow-cond",
        "sess-std",
        {"tier": "basic", "message": "hi"},
        graph=graph,
        session_manager=FlowSessionManager(redis_client=InMemoryAsyncRedis()),
        node_registry=registry,
    )
    assert "std_msg" in std.path
    assert "vip_msg" not in std.path
    assert std.variables["branch"] == "false"


@pytest.mark.asyncio
async def test_llm_node_renders_prompt_calls_gateway_stores_response() -> None:
    org_id = uuid.uuid4()
    gateway = MagicMock()
    gateway.complete_for_organization = AsyncMock(
        return_value=LLMResponse(
            content="AI says hello",
            tool_calls=None,
            prompt_tokens=5,
            completion_tokens=3,
            model_name="gpt-4o-mini",
            raw={"billing": {"credits": 2, "reference_id": "ref-1"}},
        )
    )
    registry = build_default_node_registry(llm_handler=LLMNodeHandler(gateway=gateway))

    graph = {
        "nodes": [
            {"id": "trigger", "type": "trigger", "data": {}},
            {
                "id": "llm",
                "type": "llm",
                "data": {
                    "prompt_context": "You help {{name}}",
                    "prompt_modifier": "Be concise.",
                    "user_message": "{{message_text}}",
                    "model_name": "gpt-4o",
                    "temperature": 0.2,
                    "output_variable": "llm_response",
                },
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "end"},
        ],
    }

    db = MagicMock()
    result = await execute_flow(
        db,
        "flow-llm",
        "sess-llm",
        {"name": "Aigerim", "message": "Need help", "sender_id": "42"},
        graph=graph,
        session_manager=FlowSessionManager(redis_client=InMemoryAsyncRedis()),
        organization_id=org_id,
        node_registry=registry,
    )

    assert result.variables["llm_response"] == "AI says hello"
    assert result.variables["llm_model_name"] == "gpt-4o-mini"
    assert result.variables["llm_prompt_tokens"] == 5
    assert result.variables["llm_completion_tokens"] == 3
    gateway.complete_for_organization.assert_awaited_once()
    call = gateway.complete_for_organization.await_args
    assert call.args[1] == org_id
    messages = call.args[2]
    assert messages[0]["role"] == "system"
    assert "Aigerim" in messages[0]["content"]
    assert "Be concise." in messages[0]["content"]
    assert messages[1]["content"] == "Need help"
    assert call.kwargs["temperature"] == 0.2
    assert call.kwargs["model"] == "gpt-4o"
    llm_out = next(o for o in result.outputs if o.get("event") == "llm")
    assert llm_out["billing"]["credits"] == 2
    assert llm_out["model_name"] == "gpt-4o-mini"
    assert llm_out["prompt_tokens"] == 5
    assert llm_out["completion_tokens"] == 3


@pytest.mark.asyncio
async def test_api_request_ssrf_blocks_localhost_and_metadata() -> None:
    handler = ApiRequestNodeHandler()
    registry = build_default_node_registry(api_handler=handler)
    manager = FlowSessionManager(redis_client=InMemoryAsyncRedis())
    engine = FlowExecutionEngine(manager, node_registry=registry)
    session = await manager.get_or_create(session_id="ssrf", flow_id="f")

    for bad_url in (
        "http://127.0.0.1/secret",
        "https://127.0.0.1/secret",
        "https://169.254.169.254/latest/meta-data/",
        "http://localhost/admin",
    ):
        node = {
            "id": "api",
            "type": "api_request",
            "data": {"url": bad_url, "method": "GET"},
        }
        with pytest.raises(FlowEngineError, match="SSRF"):
            await engine.execute_node(
                node,
                session=session,
                variables={},
                initial_input={},
            )


@pytest.mark.asyncio
async def test_api_request_allows_public_https_with_mock() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(200, json={"ok": True, "echo": "public"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        registry = build_default_node_registry(
            api_handler=ApiRequestNodeHandler(http_client=client)
        )
        result = await execute_flow(
            None,
            "flow-api",
            "sess-api",
            {"message": "x"},
            graph={
                "nodes": [
                    {"id": "trigger", "type": "trigger", "data": {}},
                    {
                        "id": "api",
                        "type": "api_request",
                        "data": {
                            "url": "https://example.com/v1/ping",
                            "method": "GET",
                            "response_variable": "api_response",
                        },
                    },
                    {"id": "end", "type": "end", "data": {}},
                ],
                "edges": [
                    {"id": "e1", "source": "trigger", "target": "api"},
                    {"id": "e2", "source": "api", "target": "end"},
                ],
            },
            session_manager=FlowSessionManager(redis_client=InMemoryAsyncRedis()),
            node_registry=registry,
        )

    assert captured["method"] == "GET"
    assert captured["url"].startswith("https://example.com/")
    assert result.variables["api_response"] == {"ok": True, "echo": "public"}
    assert result.variables["api_status_code"] == 200


@pytest.mark.asyncio
async def test_crm_action_creates_contact_via_injected_service() -> None:
    org_id = uuid.uuid4()
    created_id = uuid.uuid4()

    async def fake_create_contact(db, organization_id, **kwargs):
        assert organization_id == org_id
        assert kwargs["first_name"] == "Aigerim"
        return {"id": str(created_id), "first_name": kwargs["first_name"]}

    registry = build_default_node_registry(
        crm_handler=CrmActionNodeHandler(create_contact_fn=fake_create_contact)
    )
    result = await execute_flow(
        MagicMock(),
        "flow-crm",
        "sess-crm",
        {"first_name": "Aigerim", "message": "hi", "sender_id": "7700"},
        graph={
            "nodes": [
                {"id": "trigger", "type": "trigger", "data": {}},
                {
                    "id": "crm",
                    "type": "crm_action",
                    "data": {"action": "create_contact", "first_name": "{{first_name}}"},
                },
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"id": "e1", "source": "trigger", "target": "crm"},
                {"id": "e2", "source": "crm", "target": "end"},
            ],
        },
        session_manager=FlowSessionManager(redis_client=InMemoryAsyncRedis()),
        organization_id=org_id,
        node_registry=registry,
    )

    assert result.variables["crm_contact_id"] == str(created_id)
    assert result.variables["crm_last_action"] == "create_contact"


@pytest.mark.asyncio
async def test_crm_action_creates_deal_via_injected_service() -> None:
    org_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    stage_id = uuid.uuid4()
    deal_id = uuid.uuid4()

    async def fake_create_deal(db, organization_id, **kwargs):
        assert kwargs["pipeline_id"] == pipeline_id
        assert kwargs["stage_id"] == stage_id
        assert kwargs["amount"] == Decimal("1500")
        return {"id": str(deal_id), "title": kwargs["title"]}

    registry = build_default_node_registry(
        crm_handler=CrmActionNodeHandler(create_deal_fn=fake_create_deal)
    )
    result = await execute_flow(
        MagicMock(),
        "flow-deal",
        "sess-deal",
        {
            "message": "x",
            "pipeline_id": str(pipeline_id),
            "stage_id": str(stage_id),
            "deal_amount": "1500",
        },
        graph={
            "nodes": [
                {"id": "trigger", "type": "trigger", "data": {}},
                {
                    "id": "crm",
                    "type": "crm_action",
                    "data": {"action": "create_deal", "title": "From flow"},
                },
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"id": "e1", "source": "trigger", "target": "crm"},
                {"id": "e2", "source": "crm", "target": "end"},
            ],
        },
        session_manager=FlowSessionManager(redis_client=InMemoryAsyncRedis()),
        organization_id=org_id,
        node_registry=registry,
    )
    assert result.variables["crm_deal_id"] == str(deal_id)


@pytest.mark.asyncio
async def test_registry_lists_required_node_types() -> None:
    registry = build_default_node_registry()
    available = set(registry.available())
    for required in ("trigger", "condition", "llm", "api_request", "crm_action"):
        assert required in available
