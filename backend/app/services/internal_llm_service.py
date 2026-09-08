"""Unified LLM gateway access for sandbox, flow parser, and background tools."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.llm.base import InsufficientCreditsForLLMError, LLMProviderError, LLMResponse
from app.services.llm.pricing import normalize_model_name

DEFAULT_INTERNAL_MODEL = (
    getattr(settings, "OPENAI_FALLBACK_MODEL", None) or "gpt-4o-mini"
)


def _mask_key(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "missing"
    if len(raw) <= 8:
        return "***"
    return f"{raw[:4]}…{raw[-4:]} (len={len(raw)})"


_credentials_logged = False


def log_llm_credentials_status(*, source: str = "internal_llm") -> None:
    """Log whether production LLM keys are loaded (never print full secrets)."""
    global _credentials_logged
    if _credentials_logged:
        return
    _credentials_logged = True
    openai_key = getattr(settings, "OPENAI_API_KEY", None)
    openrouter_key = getattr(settings, "OPENROUTER_API_KEY", None)
    groq_key = getattr(settings, "GROQ_API_KEY", None)
    gemini_key = getattr(settings, "GEMINI_API_KEY", None)
    logger.info(
        "LLM.credentials | source={source} provider={provider} "
        "OPENAI_API_KEY={openai} OPENROUTER_API_KEY={openrouter} GROQ_API_KEY={groq} "
        "GEMINI_API_KEY={gemini} "
        "primary_model={primary} fallback_provider={fb_provider} fallback_model={fb_model} "
        "base_url={base}",
        source=source,
        provider=(settings.LLM_PROVIDER or "").strip() or "auto",
        openai=_mask_key(openai_key),
        openrouter=_mask_key(openrouter_key),
        groq=_mask_key(groq_key),
        gemini=_mask_key(gemini_key),
        primary=getattr(settings, "resolved_chat_model", None) or settings.OPENAI_CHAT_MODEL,
        fb_provider=getattr(settings, "FALLBACK_LLM_PROVIDER", None) or "-",
        fb_model=getattr(settings, "FALLBACK_LLM_MODEL", None)
        or getattr(settings, "OPENAI_FALLBACK_MODEL", None)
        or "-",
        base=getattr(settings, "resolved_openai_base_url", None) or "-",
    )


async def resolve_bot_organization_id(
    db: AsyncSession,
    bot_id: uuid.UUID,
) -> uuid.UUID | None:
    """Resolve tenant organization for a bot (direct FK or owner company)."""
    from app.models.core_models import Bot
    from app.models.users import User

    bot = await db.get(Bot, bot_id)
    if bot is None:
        return None

    org_id = getattr(bot, "organization_id", None)
    if org_id is not None:
        return org_id

    owner = await db.get(User, bot.user_id)
    if owner is not None:
        company_id = getattr(owner, "company_id", None)
        if company_id is not None:
            return uuid.UUID(str(company_id))
    return None


async def complete_via_gateway(
    db: AsyncSession,
    organization_id: uuid.UUID,
    messages: list[dict[str, Any]],
    *,
    model_name: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 1000,
    reference_id: str | None = None,
    bot_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    source: str = "internal",
    tools: list[dict[str, Any]] | None = None,
) -> LLMResponse:
    """
    Org-billed completion through ``ResilientLLMGateway`` (preflight + metering).

    Raises ``InsufficientCreditsForLLMError`` when the wallet is underfunded.
    Gateway itself retries ``FALLBACK_LLM_PROVIDER`` on 429 / 503 / timeout.
    """
    from app.services.llm.factory import get_llm_gateway

    log_llm_credentials_status(source=source)
    gateway = get_llm_gateway(include_unconfigured=True)
    model = normalize_model_name(
        settings.effective_chat_model(model_name or DEFAULT_INTERNAL_MODEL)
    )
    ref = (reference_id or "").strip() or f"{source}-{bot_id or 'na'}-{uuid.uuid4()}"

    try:
        response = await gateway.complete_for_organization(
            db,
            organization_id,
            messages,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reference_id=ref,
            bot_id=bot_id,
            user_id=user_id,
        )
    except InsufficientCreditsForLLMError:
        raise
    except LLMProviderError as exc:
        logger.error(
            "InternalLLM.gateway_failed | org={org} source={source} error={error}\n{traceback}",
            org=organization_id,
            source=source,
            error=f"{type(exc).__name__}: {exc}",
            traceback=__import__("traceback").format_exc(),
        )
        # Last resort: platform settings.OPENAI_API_KEY (or OpenRouter / Groq).
        platform_key = (
            settings.OPENAI_API_KEY
            or getattr(settings, "OPENROUTER_API_KEY", None)
            or getattr(settings, "GROQ_API_KEY", None)
        )
        if not platform_key:
            raise
        logger.warning(
            "InternalLLM.platform_key_fallback | org={org} source={source} "
            "reason=org_gateway_exhausted using=settings.OPENAI_API_KEY_chain",
            org=organization_id,
            source=source,
        )
        try:
            from app.services.llm.client import OpenAIChatClient

            client = OpenAIChatClient()
            fb = await client.chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                tools=tools,
                api_key=platform_key,
                base_url=getattr(settings, "resolved_openai_base_url", None),
            )
            return LLMResponse(
                content=(fb.text or "").strip(),
                tool_calls=list(fb.tool_calls) if fb.tool_calls else None,
                prompt_tokens=fb.input_tokens,
                completion_tokens=fb.output_tokens,
                model_name=fb.model or model,
            )
        except Exception as platform_exc:
            logger.error(
                "InternalLLM.platform_key_fallback_failed | org={org} error={error}\n{traceback}",
                org=organization_id,
                error=f"{type(platform_exc).__name__}: {platform_exc}",
                traceback=__import__("traceback").format_exc(),
            )
            raise exc from platform_exc

    logger.info(
        "InternalLLM.gateway_success | org={org} source={source} model={model} "
        "prompt_tokens={pt} completion_tokens={ct}",
        org=organization_id,
        source=source,
        model=response.model_name,
        pt=response.prompt_tokens,
        ct=response.completion_tokens,
    )
    return response


async def complete_for_bot(
    db: AsyncSession,
    bot_id: uuid.UUID,
    messages: list[dict[str, Any]],
    *,
    model_name: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 1000,
    source: str = "internal",
) -> LLMResponse | None:
    """Gateway completion scoped to a bot's organization; returns None when org is unknown."""
    org_id = await resolve_bot_organization_id(db, bot_id)
    if org_id is None:
        return None
    return await complete_via_gateway(
        db,
        org_id,
        messages,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        bot_id=bot_id,
        source=source,
    )
