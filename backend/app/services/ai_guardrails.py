"""AI safety — prompt injection heuristics + optional OpenAI moderation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.saas_metering import ModerationAction, ModerationEvent

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.I),
    re.compile(r"disregard\s+(your|the)\s+system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+DAN", re.I),
    re.compile(r"<\s*/?\s*system\s*>", re.I),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.I),
]


@dataclass(slots=True)
class GuardrailResult:
    allowed: bool
    action: ModerationAction
    reason: str
    redacted_text: str


class AIGuardrailsService:
    def enabled(self) -> bool:
        return bool(settings.AI_GUARDRAILS_ENABLED)

    async def check_text(
        self,
        db: AsyncSession | None,
        *,
        text: str,
        direction: str = "inbound",
        bot_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> GuardrailResult:
        if not self.enabled():
            return GuardrailResult(True, ModerationAction.ALLOW, "disabled", text)

        sample = (text or "")[:2000]
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(sample):
                result = GuardrailResult(
                    False, ModerationAction.BLOCK, f"injection:{pattern.pattern[:40]}", sample
                )
                await self._audit(db, result, direction, bot_id, user_id, score=None)
                return result

        if settings.AI_MODERATION_ENABLED and settings.OPENAI_API_KEY:
            flagged, score = await self._openai_moderate(sample)
            if flagged:
                result = GuardrailResult(False, ModerationAction.BLOCK, "openai_moderation", sample)
                await self._audit(db, result, direction, bot_id, user_id, score=score)
                return result

        # Soft length guard
        max_chars = settings.MAX_PROMPT_CHARS
        if len(sample) > max_chars:
            redacted = sample[:max_chars]
            result = GuardrailResult(True, ModerationAction.REDACT, "truncated", redacted)
            await self._audit(db, result, direction, bot_id, user_id, score=None)
            return result

        return GuardrailResult(True, ModerationAction.ALLOW, "ok", text)

    async def _openai_moderate(self, text: str) -> tuple[bool, Decimal | None]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.moderations.create(model="omni-moderation-latest", input=text)
            row = resp.results[0]
            flagged = bool(getattr(row, "flagged", False))
            score = None
            cats = getattr(row, "category_scores", None)
            if cats is not None:
                vals = [float(v) for v in dict(cats).values()]
                score = Decimal(str(max(vals))) if vals else None
            return flagged, score
        except Exception as exc:
            logger.warning("Guardrails.moderation_failed | error={error}", error=str(exc))
            return False, None

    async def _audit(
        self,
        db: AsyncSession | None,
        result: GuardrailResult,
        direction: str,
        bot_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        score: Decimal | None,
    ) -> None:
        if db is None or result.action == ModerationAction.ALLOW:
            return
        db.add(
            ModerationEvent(
                bot_id=bot_id,
                user_id=user_id,
                direction=direction,
                action=result.action,
                reason=result.reason,
                score=score,
                sample=result.sample[:1000],
            )
        )
        try:
            await db.flush()
        except Exception:
            logger.exception("Guardrails.audit_failed")


ai_guardrails_service = AIGuardrailsService()
