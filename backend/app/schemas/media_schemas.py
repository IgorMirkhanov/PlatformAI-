"""Outbound rich-media attachment models shared by orchestrator + channel dispatch."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


MediaKind = Literal["image", "document", "video", "audio"]


class MediaAttachment(BaseModel):
    """A file/image URL that should be delivered alongside the LLM text reply."""

    model_config = {"extra": "ignore"}

    url: str = Field(..., min_length=8, max_length=2048)
    media_type: MediaKind = "document"
    filename: str | None = Field(default=None, max_length=255)
    caption: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=128)
    source: str | None = Field(
        default=None,
        description="Origin of the attachment (rag | llm_hint | manual).",
        max_length=64,
    )
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("url")
    @classmethod
    def _must_look_like_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("Attachment URL must be an absolute http(s) URL.")
        return cleaned


# Keep HttpUrl import referenced for future strict validation helpers.
_ = HttpUrl
