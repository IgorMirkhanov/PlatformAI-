"""Unified LLM credit billing for gateway and orchestrator entry points."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.pricing import LLM_TX_TYPE, calculate_cost


async def charge_llm_credits(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    reference_id: str,
    wallet_service: Any | None = None,
) -> dict[str, Any]:
    """
    Debit organization credit wallet for one LLM completion.

    Idempotent when ``reference_id`` matches an existing ledger row.
    """
    from app.services.billing.wallet_service import (
        InsufficientFundsError,
        wallet_service as default_wallet_service,
    )
    from app.services.llm.base import InsufficientCreditsForLLMError

    wallet = wallet_service or default_wallet_service

    credits = calculate_cost(model_name, prompt_tokens, completion_tokens)
    billing_meta: dict[str, Any] = {
        "credits": credits,
        "reference_id": reference_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "model_name": model_name,
    }

    if credits <= 0:
        billing_meta["idempotent_replay"] = False
        billing_meta["skipped"] = "zero_cost"
        return billing_meta

    try:
        result = await wallet.deduct_credits(
            db,
            organization_id,
            credits,
            LLM_TX_TYPE,
            reference_id=reference_id,
        )
    except InsufficientFundsError as exc:
        raise InsufficientCreditsForLLMError(
            str(exc),
            organization_id=organization_id,
            balance=exc.balance,
            required=exc.required,
            cause=exc,
        ) from exc

    billing_meta["idempotent_replay"] = result.idempotent_replay
    billing_meta["balance_after"] = result.balance_after
    billing_meta["transaction_id"] = (
        str(result.transaction_id) if result.transaction_id else None
    )
    return billing_meta


async def record_llm_usage_event(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    bot_id: uuid.UUID | None,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    credits: int,
    reference_id: str,
    source: str,
) -> None:
    """Analytics meter only — wallet debit must already be settled."""
    if user_id is None:
        logger.debug(
            "LLMBilling.usage_skipped | org={org} reason=no_user ref={ref}",
            org=organization_id,
            ref=reference_id,
        )
        return
    try:
        from app.models.saas_metering import UsageMetricType
        from app.services.usage_service import usage_service

        total_tokens = int(prompt_tokens) + int(completion_tokens)
        await usage_service.record_and_debit(
            db,
            user_id=user_id,
            organization_id=organization_id,
            bot_id=bot_id,
            metric_type=UsageMetricType.LLM_TOKENS,
            quantity=total_tokens,
            unit_cost=Decimal(credits) / Decimal(total_tokens) if total_tokens else 0,
            currency="CREDITS",
            debit_wallet=False,
            meta={
                "reference_id": reference_id,
                "credits": credits,
                "model_name": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "source": source,
            },
        )
    except Exception as exc:
        logger.warning(
            "LLMBilling.usage_event_failed | org={org} ref={ref} error={error}",
            org=organization_id,
            ref=reference_id,
            error=str(exc),
        )
