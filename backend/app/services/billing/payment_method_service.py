"""Persist and resolve org saved payment tokens (TipTop Pay)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing.payment_method import OrganizationPaymentMethod


class PaymentMethodService:
    async def get_default_token(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        provider: str = "tiptop",
    ) -> OrganizationPaymentMethod | None:
        return await db.scalar(
            select(OrganizationPaymentMethod)
            .where(
                OrganizationPaymentMethod.organization_id == organization_id,
                OrganizationPaymentMethod.provider == provider,
                OrganizationPaymentMethod.is_default.is_(True),
            )
            .limit(1)
        )

    async def upsert_default(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        provider: str,
        token: str,
        card_last_four: str | None = None,
        card_type: str | None = None,
    ) -> OrganizationPaymentMethod:
        token_norm = token.strip()
        if not token_norm:
            raise ValueError("payment token must not be empty")

        existing = await self.get_default_token(db, organization_id, provider=provider)
        if existing is not None:
            existing.token = token_norm
            existing.card_last_four = (card_last_four or existing.card_last_four or "")[:4] or None
            existing.card_type = card_type or existing.card_type
            existing.is_default = True
            await db.flush()
            return existing

        row = OrganizationPaymentMethod(
            organization_id=organization_id,
            provider=provider,
            token=token_norm,
            card_last_four=(card_last_four or "")[:4] or None,
            card_type=card_type,
            is_default=True,
        )
        db.add(row)
        await db.flush()
        return row


payment_method_service = PaymentMethodService()
