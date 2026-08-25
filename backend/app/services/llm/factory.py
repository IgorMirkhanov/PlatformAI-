"""LLM provider registry / factory — string id → adapter instance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

from loguru import logger

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider, LLMProviderError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ProviderCls = TypeVar("ProviderCls", bound=type[BaseLLMProvider])


class LLMProviderFactory:
    """
    Resolve providers by string id (``openai``, future ``anthropic`` / ``gemini``).

    New adapters register themselves via ``@LLMProviderFactory.register("id")``
    without editing factory internals.
    """

    _registry: dict[str, type[BaseLLMProvider]] = {}

    @classmethod
    def register(cls, provider_id: str) -> Callable[[ProviderCls], ProviderCls]:
        key = provider_id.strip().lower()

        def decorator(provider_cls: ProviderCls) -> ProviderCls:
            cls._registry[key] = provider_cls
            provider_cls.provider_id = key  # type: ignore[attr-defined]
            return provider_cls

        return decorator

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._registry.keys())

    @classmethod
    def create(
        cls,
        provider_id: str | None = None,
        **kwargs: Any,
    ) -> BaseLLMProvider:
        resolved = cls.resolve_provider_id(provider_id)
        provider_cls = cls._registry.get(resolved)
        if provider_cls is None:
            known = ", ".join(cls.available()) or "(none)"
            raise LLMProviderError(
                f"Unknown LLM provider '{resolved}'. Registered: {known}.",
                provider=resolved,
            )
        instance = provider_cls(**kwargs)
        logger.debug(
            "LLMFactory.created | provider={provider} class={cls}",
            provider=resolved,
            cls=provider_cls.__name__,
        )
        return instance

    @classmethod
    def resolve_provider_id(cls, provider_id: str | None = None) -> str:
        """
        Pick provider id from argument or settings.

        ``auto`` → ``openai`` when ``OPENAI_API_KEY`` is set, else first registered.
        """
        raw = (
            provider_id
            or getattr(settings, "DEFAULT_LLM_PROVIDER", None)
            or getattr(settings, "LLM_PROVIDER", None)
            or "openai"
        )
        key = str(raw).strip().lower()
        if key in {"", "auto"}:
            if getattr(settings, "GROQ_API_KEY", None) and "groq" in cls._registry:
                return "groq"
            if (
                getattr(settings, "OPENROUTER_API_KEY", None)
                or (
                    getattr(settings, "OPENAI_API_KEY", None)
                    and "openrouter.ai" in str(getattr(settings, "OPENAI_BASE_URL", "") or "")
                )
            ) and "openrouter" in cls._registry:
                return "openrouter"
            if getattr(settings, "OPENAI_API_KEY", None) and "openai" in cls._registry:
                return "openai"
            if cls._registry:
                return next(iter(sorted(cls._registry.keys())))
            return "openai"
        return key

    @classmethod
    def resolve_for_model(cls, model_name: str | None) -> str:
        """Resolve backend id for a chat model (pricing / routing table)."""
        from app.services.llm.pricing import resolve_provider_for_model

        return resolve_provider_for_model(model_name)

    @classmethod
    def create_for_model(cls, model_name: str | None, **kwargs: Any) -> BaseLLMProvider:
        """Instantiate the adapter that owns ``model_name``."""
        from app.services.llm_model_registry import get_cached_model
        from app.services.llm_model_service import llm_model_service

        cached = get_cached_model(model_name)
        if cached is not None and cached.is_active:
            return llm_model_service.instantiate_provider(
                cached,
                api_key=kwargs.get("api_key"),
            )
        return cls.create(cls.resolve_for_model(model_name), **kwargs)


def get_llm_provider(provider_id: str | None = None, **kwargs: Any) -> BaseLLMProvider:
    """Convenience: ensure providers package is imported, then create."""
    # Side-effect import registers built-in adapters.
    import app.services.llm.providers  # noqa: F401

    return LLMProviderFactory.create(provider_id, **kwargs)


def build_gateway_providers(
    *,
    include_unconfigured: bool = True,
    org_api_keys: dict[str, str] | None = None,
) -> list[BaseLLMProvider]:
    """
    Ordered multi-vendor chain for ``ResilientLLMGateway``.

    Key resolution per provider (highest priority first):
      1. ``org_api_keys[provider_id]`` — decrypted ``OrganizationApiKey`` (tenant BYOK)
      2. Provider constructor → ``settings.<PROVIDER>_API_KEY`` / ``OPENAI_API_KEY``

    Missing a single vendor key does **not** break the chain: that adapter is
    either omitted (when ``include_unconfigured=False``) or appended as a keyless
    stub that the gateway will never promote ahead of a configured vendor.
    """
    import app.services.llm.providers  # noqa: F401

    org_keys = org_api_keys or {}
    preferred_order = (
        "openai",
        "openrouter",
        "groq",
        "anthropic",
        "gemini",
        "deepseek",
        "glm",
        "qwen",
        "ollama",
    )
    configured_provider = str(
        getattr(settings, "LLM_PROVIDER", None)
        or getattr(settings, "DEFAULT_LLM_PROVIDER", None)
        or ""
    ).strip().lower()
    if configured_provider and configured_provider not in {"", "auto"}:
        preferred_order = (configured_provider,) + tuple(
            pid for pid in preferred_order if pid != configured_provider
        )

    # FALLBACK_LLM_PROVIDER must sit directly behind the primary so a 429 / 5xx /
    # timeout / unknown-model failure lands on it instead of an unrelated vendor.
    fallback_provider = str(getattr(settings, "FALLBACK_LLM_PROVIDER", "") or "").strip().lower()
    if (
        fallback_provider
        and fallback_provider not in {"", "auto"}
        and fallback_provider != configured_provider
        and fallback_provider in preferred_order
    ):
        rest = tuple(pid for pid in preferred_order if pid != fallback_provider)
        preferred_order = rest[:1] + (fallback_provider,) + rest[1:]

    fallback_model = str(getattr(settings, "FALLBACK_LLM_MODEL", "") or "").strip()
    configured: list[BaseLLMProvider] = []
    stubs: list[BaseLLMProvider] = []

    for provider_id in preferred_order:
        if provider_id not in LLMProviderFactory._registry:
            continue
        kwargs: dict[str, Any] = {}
        if provider_id in org_keys:
            kwargs["api_key"] = org_keys[provider_id]
        if (
            provider_id == fallback_provider
            and provider_id != configured_provider
            and fallback_model
        ):
            kwargs["model"] = fallback_model
        try:
            instance = LLMProviderFactory.create(provider_id, **kwargs)
        except Exception as exc:
            logger.debug(
                "LLMFactory.provider_skipped | provider={provider} error={error}",
                provider=provider_id,
                error=str(exc),
            )
            continue
        has_key = bool(getattr(instance, "api_key", None))
        if has_key:
            configured.append(instance)
        elif include_unconfigured:
            stubs.append(instance)
        else:
            logger.debug(
                "LLMFactory.provider_unconfigured | provider={provider} — omitted",
                provider=provider_id,
            )

    if configured:
        return configured + stubs
    if stubs:
        return stubs
    return [get_llm_provider()]


async def build_gateway_providers_for_organization(
    db: AsyncSession,
    organization_id: Any,
    *,
    include_unconfigured: bool = True,
) -> list[BaseLLMProvider]:
    """Build provider chain using decrypted organization API keys when present."""
    from app.services.ai_keys_service import ai_keys_service
    from app.services.llm_model_registry import ensure_model_cache
    from app.services.llm_model_service import llm_model_service

    org_keys = await ai_keys_service.get_active_keys_map(db, organization_id)
    models = await ensure_model_cache(db)
    dynamic_providers = llm_model_service.build_dynamic_providers(models, org_api_keys=org_keys)
    base_providers = build_gateway_providers(
        include_unconfigured=include_unconfigured,
        org_api_keys=org_keys,
    )

    merged: list[BaseLLMProvider] = []
    seen_keys: set[str] = set()

    def _add(provider: BaseLLMProvider) -> None:
        model = str(getattr(provider, "model", "") or "")
        base_url = str(getattr(provider, "base_url", "") or "")
        pid = str(getattr(provider, "provider_id", "") or type(provider).__name__)
        key = f"{pid}:{model}:{base_url}"
        if key in seen_keys:
            return
        seen_keys.add(key)
        merged.append(provider)

    for provider in dynamic_providers + base_providers:
        _add(provider)

    return merged or base_providers


def get_llm_gateway(*, include_unconfigured: bool = True) -> Any:
    """Build a resilient gateway with the default multi-provider chain."""
    from app.services.llm.gateway import ResilientLLMGateway

    return ResilientLLMGateway(
        build_gateway_providers(include_unconfigured=include_unconfigured)
    )
