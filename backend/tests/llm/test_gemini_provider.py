"""Google AI Studio Gemini adapter (OpenAI-compatible endpoint)."""

from __future__ import annotations

from app.services.llm.providers.openai_provider import gemini_compatible_messages
from app.services.llm.providers.stub_providers import GeminiProvider


def test_gemini_provider_uses_google_openai_compat_url() -> None:
    provider = GeminiProvider(api_key="test-ai-studio-key", model="gemini-2.5-flash")
    assert provider.provider_id == "gemini"
    assert provider.api_key == "test-ai-studio-key"
    assert "generativelanguage.googleapis.com" in (provider.base_url or "")
    assert provider.model == "gemini-2.5-flash"


def test_gemini_compatible_messages_fold_system_and_drop_empty() -> None:
    folded = gemini_compatible_messages(
        [
            {"role": "system", "content": "You are a travel agent."},
            {"role": "assistant", "content": "   "},
            {"role": "user", "content": "Сколько стоит доставка?"},
        ]
    )
    assert len(folded) == 1
    assert folded[0]["role"] == "user"
    assert folded[0]["content"].startswith("You are a travel agent.")
    assert "Сколько стоит доставка?" in folded[0]["content"]
