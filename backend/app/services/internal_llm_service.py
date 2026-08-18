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
    """
    from app.services.llm.factory import get_llm_gateway

    gateway = get_llm_gateway(include_unconfigured=True)
    model = normalize_model_name(model_name or DEFAULT_INTERNAL_MODEL)
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
        logger.warning(
            "InternalLLM.gateway_failed | org={org} source={source} error={error}",
            org=organization_id,
            source=source,
            error=str(exc),
        )
        raise

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
