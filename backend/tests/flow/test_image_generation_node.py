"""Unit tests for ImageGenerationNodeHandler."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.billing.wallet_service import DeductResult, InsufficientFundsError
from app.services.flow.engine import FlowEngineError, FlowSessionState
from app.services.flow.nodes.base import NodeExecutionContext
from app.services.flow.nodes.image_generation_node import ImageGenerationNodeHandler
from app.services.media.base_media import MediaGenerationResult

SESSION_ID = str(uuid.uuid4())
ORG_ID = uuid.uuid4()


class _FakeRegistry:
    def __init__(self, result: MediaGenerationResult) -> None:
        self._result = result
        self.last_provider: str | None = None

    def get_connector(self, name: str, **kwargs: Any) -> Any:
        self.last_provider = name
        connector = MagicMock()
        connector.generate_image = AsyncMock(return_value=self._result)
        return connector


def _make_ctx(
    data: dict[str, Any],
    variables: dict[str, Any] | None = None,
    *,
    db: Any | None = None,
) -> NodeExecutionContext:
    session = FlowSessionState(session_id=SESSION_ID, flow_id="flow-1")
    return NodeExecutionContext(
        node={"id": "img-1", "type": "image_generation", "data": data},
        session=session,
        variables=variables or {},
        initial_input={},
        organization_id=ORG_ID,
        db=db or MagicMock(),
    )


@pytest.mark.asyncio
async def test_image_generation_node_renders_prompt_and_stores_url() -> None:
    fake_result = MediaGenerationResult(
        url="https://cdn.example/generated.png",
        provider="kling",
        revised_prompt="refined prompt",
    )
    handler = ImageGenerationNodeHandler(registry=_FakeRegistry(fake_result))  # type: ignore[arg-type]
    ctx = _make_ctx(
        {
            "provider": "kling",
            "model_name": "kling-v1",
            "prompt_template": "Create a banner for {{ session.variables.product_name }}",
            "aspect_ratio": "16:9",
            "result_variable": "hero_image",
        },
        {"product_name": "MP.AI Pro"},
    )

    deduct = DeductResult(
        organization_id=ORG_ID,
        amount=500,
        balance_before=5000,
        balance_after=4500,
        transaction_id=uuid.uuid4(),
        idempotent_replay=False,
    )

    with patch(
        "app.services.billing.wallet_service.wallet_service.deduct_credits",
        new=AsyncMock(return_value=deduct),
    ) as deduct_mock:
        result = await handler.execute(ctx)

    deduct_mock.assert_awaited_once()
    args = deduct_mock.await_args.args
    assert args[1] == ORG_ID
    assert args[2] == 500
    assert result.event == "image_generation"
    assert ctx.variables["hero_image"] == "https://cdn.example/generated.png"
    assert result.output["billing"]["credits"] == 500


@pytest.mark.asyncio
async def test_image_generation_node_nanobanana_provider() -> None:
    registry = _FakeRegistry(
        MediaGenerationResult(url="https://cdn.example/nb.png", provider="nanobanana")
    )
    handler = ImageGenerationNodeHandler(registry=registry)  # type: ignore[arg-type]
    ctx = _make_ctx(
        {
            "provider": "nanobanana",
            "prompt_template": "Studio photo of {{ brand }}",
            "aspect_ratio": "1:1",
            "result_variable": "product_image",
        },
        {"brand": "Nano Banana"},
    )

    with patch(
        "app.services.billing.wallet_service.wallet_service.deduct_credits",
        new=AsyncMock(
            return_value=DeductResult(
                organization_id=ORG_ID,
                amount=600,
                balance_before=2000,
                balance_after=1400,
                transaction_id=uuid.uuid4(),
            )
        ),
    ):
        await handler.execute(ctx)

    assert registry.last_provider == "nanobanana"
    assert ctx.variables["product_image"] == "https://cdn.example/nb.png"


@pytest.mark.asyncio
async def test_image_generation_insufficient_credits_raises() -> None:
    handler = ImageGenerationNodeHandler(registry=_FakeRegistry(  # type: ignore[arg-type]
        MediaGenerationResult(url="https://cdn.example/x.png", provider="kling")
    ))
    ctx = _make_ctx(
        {
            "provider": "kling",
            "prompt_template": "A cat",
            "result_variable": "image_url",
        }
    )

    with patch(
        "app.services.billing.wallet_service.wallet_service.deduct_credits",
        new=AsyncMock(
            side_effect=InsufficientFundsError(
                balance=10,
                required=500,
                organization_id=ORG_ID,
            )
        ),
    ), pytest.raises(FlowEngineError, match="Insufficient credits"):
        await handler.execute(ctx)


@pytest.mark.asyncio
async def test_image_generation_handler_registered_in_default_registry() -> None:
    from app.services.flow.nodes.base import build_default_node_registry

    registry = build_default_node_registry()
    handler = registry.get("image_generation")
    assert isinstance(handler, ImageGenerationNodeHandler)
