"""Credit pricing for media generation."""

from __future__ import annotations

from app.core.config import settings

IMAGE_TX_TYPE = "image_generation"


def calculate_image_credits(provider: str, model_name: str | None = None) -> int:
    """
    Return integer credits to charge for one image generation.

    Provider-specific defaults can be overridden via environment variables.
    """
    provider_key = str(provider or "").strip().lower()
    model_key = str(model_name or "").strip().lower()

    if provider_key == "kling":
        base = int(getattr(settings, "MEDIA_IMAGE_CREDIT_KLING", 500))
        if "2" in model_key or "v2" in model_key:
            return int(getattr(settings, "MEDIA_IMAGE_CREDIT_KLING_V2", base * 2))
        return base

    if provider_key in {"nanobanana", "nano_banana", "nano-banana-pro"}:
        base = int(getattr(settings, "MEDIA_IMAGE_CREDIT_NANOBANANA", 600))
        if model_key and "4k" in model_key:
            return int(getattr(settings, "MEDIA_IMAGE_CREDIT_NANOBANANA_4K", base * 2))
        return base

    return int(getattr(settings, "MEDIA_IMAGE_CREDIT_DEFAULT", 500))
