"""Media generation contracts and provider registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class MediaGenerationRequest(BaseModel):
    """Normalized image generation input."""

    prompt: str = Field(min_length=1)
    negative_prompt: str | None = None
    width: int | None = Field(default=None, ge=64, le=4096)
    height: int | None = Field(default=None, ge=64, le=4096)
    aspect_ratio: str | None = None
    model_name: str | None = None


class MediaGenerationResult(BaseModel):
    """Provider-agnostic image generation output."""

    url: str = Field(min_length=1)
    provider: str
    revised_prompt: str | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)


class MediaGenerationError(RuntimeError):
    """Raised when a media provider fails to generate content."""


class BaseMediaConnector(ABC):
    """Adapter for one external image generation vendor."""

    provider_id: ClassVar[str] = "base"

    @abstractmethod
    async def generate_image(self, request: MediaGenerationRequest) -> MediaGenerationResult:
        """Generate an image and return a public URL."""


class MediaRegistry:
    """String provider id → connector class registry."""

    _connectors: ClassVar[dict[str, type[BaseMediaConnector]]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: ``@MediaRegistry.register("kling")``."""

        key = str(name).strip().lower()

        def decorator(connector_cls: type[BaseMediaConnector]) -> type[BaseMediaConnector]:
            cls._connectors[key] = connector_cls
            connector_cls.provider_id = key
            return connector_cls

        return decorator

    @classmethod
    def get_connector(cls, name: str, **kwargs: Any) -> BaseMediaConnector:
        key = str(name).strip().lower()
        connector_cls = cls._connectors.get(key)
        if connector_cls is None:
            known = ", ".join(sorted(cls._connectors)) or "(none)"
            raise MediaGenerationError(
                f"Unknown media provider '{name}'. Registered providers: {known}."
            )
        return connector_cls(**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._connectors.keys())


def aspect_ratio_to_dimensions(aspect_ratio: str | None) -> tuple[int | None, int | None]:
    """Map common aspect ratios to pixel dimensions for providers that need width/height."""
    mapping = {
        "1:1": (1024, 1024),
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "4:3": (1280, 960),
        "3:4": (960, 1280),
    }
    if not aspect_ratio:
        return None, None
    return mapping.get(str(aspect_ratio).strip(), (None, None))
