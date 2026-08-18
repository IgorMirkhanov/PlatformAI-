"""Unit tests for Kling and Nano Banana Pro media connectors."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.media.base_media import MediaGenerationRequest, MediaRegistry
from app.services.media.connectors import KlingMediaConnector, NanoBananaProConnector


def _mock_response(json_data: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=response,
        )
    return response


@pytest.mark.asyncio
async def test_kling_connector_generates_image_url() -> None:
    client = AsyncMock()
    client.post = AsyncMock(
        return_value=_mock_response({"data": {"task_id": "task-kling-1"}})
    )
    client.get = AsyncMock(
        return_value=_mock_response(
            {
                "data": {
                    "task_status": "succeed",
                    "task_result": {
                        "images": [{"url": "https://cdn.example/kling.png"}],
                    },
                }
            }
        )
    )

    connector = KlingMediaConnector(
        api_key="test-kling",
        base_url="https://kling.test",
        client=client,
        poll_interval=0.0,
        poll_max_attempts=2,
    )
    result = await connector.generate_image(
        MediaGenerationRequest(
            prompt="A scenic mountain landscape",
            aspect_ratio="16:9",
            model_name="kling-v1",
        )
    )

    assert result.url == "https://cdn.example/kling.png"
    assert result.provider == "kling"
    client.post.assert_awaited_once()
    payload = client.post.await_args.kwargs["json"]
    assert payload["prompt"] == "A scenic mountain landscape"
    assert payload["aspect_ratio"] == "16:9"


@pytest.mark.asyncio
async def test_nanobanana_connector_generates_image_url() -> None:
    client = AsyncMock()
    client.post = AsyncMock(
        side_effect=[
            _mock_response({"generationId": "gen-nb-42"}),
            _mock_response(
                {
                    "status": "completed",
                    "result": {"url": "https://cdn.example/nanobanana.png"},
                }
            ),
        ]
    )

    connector = NanoBananaProConnector(
        api_key="test-nb",
        base_url="https://nanobanana.test",
        client=client,
        poll_interval=0.0,
        poll_max_attempts=2,
    )
    result = await connector.generate_image(
        MediaGenerationRequest(
            prompt="Product hero shot on white background",
            aspect_ratio="1:1",
            model_name="nano-banana-pro",
        )
    )

    assert result.url == "https://cdn.example/nanobanana.png"
    assert result.provider == "nanobanana"
    assert client.post.await_count == 2


def test_media_registry_returns_registered_connectors() -> None:
    kling = MediaRegistry.get_connector("kling", api_key="k", client=MagicMock())
    nano = MediaRegistry.get_connector("nanobanana", api_key="n", client=MagicMock())
    assert isinstance(kling, KlingMediaConnector)
    assert isinstance(nano, NanoBananaProConnector)
