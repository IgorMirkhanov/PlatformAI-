"""Google AI Studio Gemini adapter (OpenAI-compatible endpoint)."""

from __future__ import annotations

from app.services.llm.providers.stub_providers import GeminiProvider


def test_gemini_provider_uses_google_openai_compat_url() -> None:
    provider = GeminiProvider(api_key="test-ai-studio-key", model="gemini-2.5-flash")
    assert provider.provider_id == "gemini"
    assert provider.api_key == "test-ai-studio-key"
    assert "generativelanguage.googleapis.com" in (provider.base_url or "")
    assert provider.model == "gemini-2.5-flash"
