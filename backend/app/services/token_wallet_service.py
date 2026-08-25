"""Token-wallet pre-check and post-LLM debit (commercial release spec §1.4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.metrics import record_wallet_blocked
from app.models.wallet import WalletStatus, WalletTxType
from app.repositories.wallet_repository import WalletDebitResult, wallet_repository


@dataclass(slots=True, frozen=True)
class WalletCheckResult:
    allowed: bool
    reason: str | None = None
    balance_tokens: int = 0
    status: str = WalletStatus.ACTIVE.value


class TokenWalletService:
    async def check_wallet_before_generation(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> WalletCheckResult:
        """Read-only. Does not take FOR UPDATE — race is resolved by debit_atomic."""
        if getattr(settings, "is_free_llm_route", False):
            return WalletCheckResult(allowed=True, reason="free_llm_route")

        wallet = await wallet_repository(db).get_by_org(org_id)
        if wallet is None:
            return WalletCheckResult(allowed=False, reason="balance_exhausted", status="missing")
        reserve = int(getattr(settings, "WALLET_MIN_TOKENS_RESERVE", 1) or 1)
        if wallet.status == WalletStatus.BLOCKED.value:
            return WalletCheckResult(
                allowed=False,
                reason="balance_exhausted",
                balance_tokens=int(wallet.balance_tokens),
                status=wallet.status,
            )
        if int(wallet.balance_tokens) < reserve:
            return WalletCheckResult(
                allowed=False,
                reason="balance_exhausted",
                balance_tokens=int(wallet.balance_tokens),
                status=wallet.status,
            )
        return WalletCheckResult(
            allowed=True,
            balance_tokens=int(wallet.balance_tokens),
            status=wallet.status,
        )

    async def debit_after_generation(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        amount_tokens: int,
        idempotency_key: str,
        bot_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        model_used: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WalletDebitResult:
        if amount_tokens <= 0:
            return WalletDebitResult(success=True, reason="zero_amount", idempotent_replay=True)
        result = await wallet_repository(db).debit_atomic(
            org_id,
            amount_tokens,
            idempotency_key,
            bot_id=bot_id,
            conversation_id=conversation_id,
            model_used=model_used,
            metadata=metadata,
        )
        if not result.success and result.reason == "insufficient_balance":
            record_wallet_blocked("debit")
            logger.warning(
                "TokenWallet.debit_blocked | org={org} remaining={bal}",
                org=org_id,
                bal=result.balance_after,
            )
        return result

    async def credit_topup(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        amount_tokens: int,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> WalletDebitResult:
        return await wallet_repository(db).credit_atomic(
            org_id,
            amount_tokens,
            WalletTxType.CREDIT_TOPUP.value,
            idempotency_key,
            metadata=metadata,
        )


token_wallet_service = TokenWalletService()
check_wallet_before_generation = token_wallet_service.check_wallet_before_generation
