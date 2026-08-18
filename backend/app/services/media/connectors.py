"""Kling AI and Nano Banana Pro image generation connectors."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.services.media.base_media import (
    BaseMediaConnector,
    MediaGenerationError,
    MediaGenerationRequest,
    MediaGenerationResult,
    MediaRegistry,
    aspect_ratio_to_dimensions,
)


def _first_url(payload: Any) -> str | None:
    if isinstance(payload, str) and payload.startswith(("http://", "https://")):
        return payload
    if isinstance(payload, dict):
        for key in ("url", "image_url", "imageUrl", "output_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        images = payload.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                url = first.get("url")
                if isinstance(url, str):
                    return url
            if isinstance(first, str):
                return first
    return None


async def _poll_until_ready(
    *,
    fetch_status: Any,
    is_ready: Any,
    extract_url: Any,
    interval: float,
    max_attempts: int,
) -> tuple[str, dict[str, Any]]:
    last_payload: dict[str, Any] = {}
    for attempt in range(max_attempts):
        last_payload = await fetch_status()
        if is_ready(last_payload):
            url = extract_url(last_payload)
            if url:
                return url, last_payload
            raise MediaGenerationError("Provider reported success but returned no image URL.")
        await asyncio.sleep(interval)
    raise MediaGenerationError(
        f"Image generation timed out after {max_attempts} status checks."
    )


@MediaRegistry.register("kling")
class KlingMediaConnector(BaseMediaConnector):
    """Kling AI text-to-image connector (async task + poll)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        client: httpx.AsyncClient | None = None,
        poll_interval: float | None = None,
        poll_max_attempts: int | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.KLING_API_KEY
        self._base_url = (base_url or settings.KLING_API_BASE_URL).rstrip("/")
        self._default_model = default_model or settings.KLING_IMAGE_MODEL
        self._client = client
        self._poll_interval = float(
            poll_interval
            if poll_interval is not None
            else settings.MEDIA_GENERATION_POLL_INTERVAL_SECONDS
        )
        self._poll_max_attempts = int(
            poll_max_attempts
            if poll_max_attempts is not None
            else settings.MEDIA_GENERATION_POLL_MAX_ATTEMPTS
        )

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise MediaGenerationError("KLING_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def generate_image(self, request: MediaGenerationRequest) -> MediaGenerationResult:
        width = request.width
        height = request.height
        if width is None or height is None:
            mapped_w, mapped_h = aspect_ratio_to_dimensions(request.aspect_ratio)
            width = width or mapped_w
            height = height or mapped_h

        payload: dict[str, Any] = {
            "model_name": request.model_name or self._default_model,
            "prompt": request.prompt,
            "n": 1,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        if width and height:
            payload["width"] = width
            payload["height"] = height

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=httpx.Timeout(60.0),
        )
        try:
            create_resp = await client.post("/v1/images/generations", json=payload)
            create_resp.raise_for_status()
            create_data = create_resp.json()
            task_id = (
                (create_data.get("data") or {}).get("task_id")
                or create_data.get("task_id")
                or (create_data.get("data") or {}).get("id")
            )
            if not task_id:
                raise MediaGenerationError(f"Kling API did not return task_id: {create_data}")

            async def fetch_status() -> dict[str, Any]:
                status_resp = await client.get(f"/v1/images/generations/{task_id}")
                status_resp.raise_for_status()
                body = status_resp.json()
                return body.get("data") if isinstance(body.get("data"), dict) else body

            def is_ready(body: dict[str, Any]) -> bool:
                status = str(body.get("task_status") or body.get("status") or "").lower()
                return status in {"succeed", "success", "completed", "done"}

            def extract_url(body: dict[str, Any]) -> str | None:
                task_result = body.get("task_result") or body.get("result") or body
                return _first_url(task_result)

            url, raw = await _poll_until_ready(
                fetch_status=fetch_status,
                is_ready=is_ready,
                extract_url=extract_url,
                interval=self._poll_interval,
                max_attempts=self._poll_max_attempts,
            )
            revised = None
            task_result = raw.get("task_result") if isinstance(raw.get("task_result"), dict) else raw
            if isinstance(task_result, dict):
                revised = task_result.get("revised_prompt") or task_result.get("prompt")

            logger.info("Media.Kling.success | task_id={task_id}", task_id=task_id)
            return MediaGenerationResult(
                url=url,
                provider="kling",
                revised_prompt=str(revised) if revised else None,
                raw_response={"create": create_data, "status": raw},
            )
        except httpx.HTTPStatusError as exc:
            raise MediaGenerationError(
                f"Kling API HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaGenerationError(f"Kling API request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()


@MediaRegistry.register("nanobanana")
class NanoBananaProConnector(BaseMediaConnector):
    """Nano Banana Pro image generation connector."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        client: httpx.AsyncClient | None = None,
        poll_interval: float | None = None,
        poll_max_attempts: int | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.NANOBANANA_API_KEY
        self._base_url = (base_url or settings.NANOBANANA_API_BASE_URL).rstrip("/")
        self._default_model = default_model or settings.NANOBANANA_IMAGE_MODEL
        self._client = client
        self._poll_interval = float(
            poll_interval
            if poll_interval is not None
            else settings.MEDIA_GENERATION_POLL_INTERVAL_SECONDS
        )
        self._poll_max_attempts = int(
            poll_max_attempts
            if poll_max_attempts is not None
            else settings.MEDIA_GENERATION_POLL_MAX_ATTEMPTS
        )

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise MediaGenerationError("NANOBANANA_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def generate_image(self, request: MediaGenerationRequest) -> MediaGenerationResult:
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "mode": "generate",
            "model": request.model_name or self._default_model,
            "aspectRatio": request.aspect_ratio or "1:1",
            "imageQuality": "1K",
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.width and request.height:
            payload["width"] = request.width
            payload["height"] = request.height

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=httpx.Timeout(60.0),
        )
        try:
            create_resp = await client.post("/api/nano-banana-pro/generate", json=payload)
            create_resp.raise_for_status()
            create_data = create_resp.json()
            generation_id = (
                create_data.get("generationId")
                or create_data.get("generation_id")
                or (create_data.get("data") or {}).get("generationId")
            )
            if not generation_id:
                # Some gateways return the image synchronously.
                direct_url = _first_url(create_data.get("data") or create_data)
                if direct_url:
                    return MediaGenerationResult(
                        url=direct_url,
                        provider="nanobanana",
                        revised_prompt=create_data.get("revised_prompt"),
                        raw_response=create_data,
                    )
                raise MediaGenerationError(
                    f"Nano Banana Pro API did not return generationId: {create_data}"
                )

            async def fetch_status() -> dict[str, Any]:
                status_resp = await client.post(
                    "/api/nano-banana-pro/check-status",
                    json={"generationId": generation_id},
                )
                status_resp.raise_for_status()
                return status_resp.json()

            def is_ready(body: dict[str, Any]) -> bool:
                status = str(body.get("status") or body.get("state") or "").lower()
                return status in {"completed", "success", "succeed", "done"}

            def extract_url(body: dict[str, Any]) -> str | None:
                return _first_url(body.get("result") or body.get("data") or body)

            url, raw = await _poll_until_ready(
                fetch_status=fetch_status,
                is_ready=is_ready,
                extract_url=extract_url,
                interval=self._poll_interval,
                max_attempts=self._poll_max_attempts,
            )
            logger.info(
                "Media.NanoBanana.success | generation_id={generation_id}",
                generation_id=generation_id,
            )
            return MediaGenerationResult(
                url=url,
                provider="nanobanana",
                revised_prompt=raw.get("revised_prompt"),
                raw_response={"create": create_data, "status": raw},
            )
        except httpx.HTTPStatusError as exc:
            raise MediaGenerationError(
                f"Nano Banana Pro API HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaGenerationError(f"Nano Banana Pro API request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()
