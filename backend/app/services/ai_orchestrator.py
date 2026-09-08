from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_cache import llm_response_cache
from app.core.vector_db import RAGSearchHit, search_knowledge_base
from app.models.core_models import (
    Bot,
    ChatMessage,
    DiagnosticErrorType,
    MessageSender,
    Organization,
    Subscription,
    SubscriptionStatus,
)
from app.schemas.media_schemas import MediaAttachment
from app.schemas.sandbox_schemas import LLMMetricsTrace, RAGChunkTrace
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.execution_trace import ExecutionTraceBuilder
from app.services.knowledge_base_service import knowledge_base_service
from app.services.llm.types import TransientLLMError
from app.services.pricing_service import pricing_service
from app.services.wallet_service import InsufficientFundsException as WalletInsufficientFundsError
from app.services.quota_service import QuotaExceeded
from app.services.media_dispatch_service import (
    HIGH_RELEVANCE_THRESHOLD,
    MEDIA_METADATA_KEYS,
    dedupe_attachments,
    extract_urls_from_metadata,
    filename_from_url,
    infer_media_kind,
)


USD_TO_KZT = float(getattr(settings, "USD_TO_KZT", 450.0) or 450.0)

# Legacy USD estimates for diagnostics only — billing uses ``app.services.llm.pricing``.
MODEL_COST_USD_PER_1K: dict[str, float] = {
    "gpt-4o-mini": 0.00015,
    "gpt-4o": 0.005,
    "llama3": 0.0,
    "claude-3.5-sonnet": 0.003,
}

WHATSAPP_FAMILY = {
    "whatsapp",
    "whatsapp_qr",
    "whatsapp-qr",
    "waba",
    "wa",
}

TELEGRAM_FAMILY = {
    "telegram",
    "telegram_business",
    "telegram-secretary",
    "tg",
}

WHATSAPP_PROMPT_ADDON = (
    "Channel style (WhatsApp): Keep responses concise. Write in short paragraphs. "
    "Use bullet points where possible. Avoid long walls of text. Use emojis moderately."
)

TELEGRAM_PROMPT_ADDON = (
    "Channel style (Telegram): You can provide deeper, formatted answers. "
    "Use MarkdownV2-compatible formatting or clean HTML tags for key text, "
    "code blocks, and bold statements when helpful."
)

LLM_MEDIA_HINT_PATTERN = re.compile(
    r"(?i)("
    r"attach(?:ed|ment)?|"
    r"send(?:ing)?\s+(?:the\s+)?(?:file|image|photo|document|pdf)|"
    r"here(?:'s| is)\s+(?:the\s+)?(?:file|image|photo|document)|"
    r"см(?:отри|отрите)\s+(?:файл|изображение|фото|документ)|"
    r"отправляю\s+(?:файл|изображение|фото|документ)"
    r")"
)

URL_IN_TEXT_PATTERN = re.compile(
    r"(https?://[^\s<>\"']+\.(?:png|jpe?g|gif|webp|bmp|pdf|docx?|xlsx?|pptx?|zip|mp4|mp3))",
    re.IGNORECASE,
)


@dataclass
class LLMCompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_hit: bool = False
    model_name: str | None = None
    # True when Gateway (or another upstream stage) already settled wallet debit.
    billing_handled: bool = False
    # Tool names executed during this completion (empty when no function calling).
    tools_executed: list[str] = field(default_factory=list)
    # True when at least one booking/CRM tool returned a successful status.
    booking_tools_succeeded: bool = False


@dataclass
class OrchestratorResult:
    """LLM text reply plus optional rich-media attachments for channel dispatch."""

    text: str
    media_attachments: list[MediaAttachment] = field(default_factory=list)

    # Allow legacy call sites that treat the result as a string via str().
    def __str__(self) -> str:
        return self.text


class InsufficientFundsError(RuntimeError):
    """Raised when subscription balance blocks LLM execution."""


class OrganizationSuspendedError(RuntimeError):
    """Raised when the tenant organization is suspended (kill switch)."""


class AIOrchestrator:
    """Builds LLM prompts from flow node config, chat history, and RAG context."""

    DEFAULT_FAST_MODEL = (
        getattr(settings, "resolved_chat_model", None)
        or getattr(settings, "OPENAI_CHAT_MODEL", None)
        or getattr(settings, "OPENAI_FALLBACK_MODEL", None)
        or "gpt-4o-mini"
    )

    FALLBACK_MESSAGE = (
        "К сожалению, сервис временно перегружен. Попробуйте написать чуть позже."
    )
    FUNDS_FALLBACK_MESSAGE = (
        "AI agent is temporarily unavailable. Transferring to an operator."
    )
    # Used when tools succeed but the model returns empty content (common with tool-only turns).
    TOOL_SUCCESS_CONFIRMATION_MESSAGE = (
        "Отлично! Записал вас на консультацию и зафиксировал заявку. "
        "Наш менеджер свяжется с вами."
    )

    BOOKING_TOOL_NAMES = frozenset(
        {
            "create_calendar_event",
            "save_lead_to_crm",
            "check_calendar_availability",
        }
    )

    async def generate_ai_response(
        self,
        client_id: uuid.UUID,
        current_node_data: dict[str, Any],
        incoming_message: str,
        db_session: AsyncSession,
        *,
        bot_id: uuid.UUID | None = None,
        node_id: str | None = None,
        channel: str | None = None,
        propagate_transient: bool = False,
        dry_run: bool = False,
    ) -> OrchestratorResult:
        logger.info(
            "AIOrchestrator.start | client_id={client_id} channel={channel} message_len={length}",
            client_id=client_id,
            channel=channel or "unknown",
            length=len(incoming_message),
        )

        try:
            if bot_id is not None:
                await self._assert_sufficient_balance(
                    db_session, bot_id, client_id, node_id=node_id
                )
                try:
                    from app.models.core_models import Bot
                    from app.services.quota_service import quota_service

                    bot = await db_session.get(Bot, bot_id)
                    org_id = getattr(bot, "organization_id", None) if bot is not None else None
                    if org_id is not None:
                        await quota_service.assert_token_quota(db_session, org_id)
                except QuotaExceeded:
                    raise
                except Exception as quota_exc:
                    logger.warning(
                        "AIOrchestrator.token_quota_check_skipped | bot_id={bot_id} error={error}",
                        bot_id=bot_id,
                        error=str(quota_exc),
                    )

            from app.services.ai_guardrails import ai_guardrails_service

            guard = await ai_guardrails_service.check_text(
                db_session,
                text=incoming_message,
                direction="inbound",
                bot_id=bot_id,
            )
            if not guard.allowed:
                from app.core.metrics import GUARDRAIL_BLOCKS

                GUARDRAIL_BLOCKS.labels(reason=guard.reason[:64]).inc()
                return OrchestratorResult(
                    text="Извините, сообщение не может быть обработано.",
                    media_attachments=[],
                )
            incoming_message = guard.redacted_text

            history = await self._fetch_chat_history(db_session, client_id)
            rag_hits, rag_context = await self._fetch_rag_context_detailed(
                db_session,
                current_node_data,
                incoming_message,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
            )
            global_prompt = await self._resolve_global_prompt(
                db_session,
                current_node_data,
                bot_id=bot_id,
            )
            system_prompt = self._apply_platform_prompt_routing(
                self._merge_prompts(
                    str(current_node_data.get("prompt_context", "") or ""),
                    global_prompt,
                ),
                channel=channel,
            )
            messages = self._build_llm_messages(
                system_prompt=system_prompt,
                rag_context=rag_context,
                history=history,
                incoming_message=incoming_message,
            )
            if history:
                # Reinforce continuity — models sometimes re-greet mid-dialog.
                messages[0]["content"] = (
                    f"{messages[0]['content']}\n\n"
                    "CONTINUITY: This is an ongoing conversation. "
                    "Do not restart with a greeting or company intro. "
                    "Answer the latest user message using prior turns."
                )
            node_model = (
                current_node_data.get("llm_model_name")
                or current_node_data.get("model_name")
                or current_node_data.get("model")
            )
            node_temperature = current_node_data.get("temperature")
            completion = await self._request_completion_with_usage(
                messages,
                model_name=str(node_model) if node_model else None,
                temperature=float(node_temperature) if node_temperature is not None else None,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                db=db_session,
                source="orchestrator",
            )
            used_model = (
                getattr(completion, "model_name", None)
                or (str(node_model) if node_model else None)
                or settings.resolved_chat_model
                or settings.OPENAI_CHAT_MODEL
            )
            if (
                bot_id is not None
                and not completion.cache_hit
                and (completion.input_tokens > 0 or completion.output_tokens > 0)
            ):
                await self._record_llm_usage_and_debit(
                    db_session,
                    bot_id=bot_id,
                    prompt_tokens=completion.input_tokens,
                    completion_tokens=completion.output_tokens,
                    model_name=used_model,
                    billing_handled=completion.billing_handled,
                    client_id=client_id,
                    dry_run=dry_run,
                )
            response_text = (completion.text or "").strip()
            from app.services.llm.tool_reply_sanitize import (
                is_tool_debug_text,
                sanitize_outbound_text,
            )

            if is_tool_debug_text(response_text) or (
                not response_text
                and (
                    completion.booking_tools_succeeded
                    or bool(completion.tools_executed)
                    or any(name in self.BOOKING_TOOL_NAMES for name in completion.tools_executed)
                )
            ):
                response_text = sanitize_outbound_text(
                    response_text,
                    tools_executed=completion.tools_executed,
                    booking_ok=completion.booking_tools_succeeded
                    or any(name in self.BOOKING_TOOL_NAMES for name in completion.tools_executed),
                    fallback=self.TOOL_SUCCESS_CONFIRMATION_MESSAGE,
                )
                logger.info(
                    "AIOrchestrator.tool_success_fallback | client_id={client_id} tools={tools}",
                    client_id=client_id,
                    tools=completion.tools_executed,
                )
            response_text = sanitize_outbound_text(response_text) or response_text
            attachments = self._collect_media_attachments(
                rag_hits=rag_hits,
                llm_text=response_text,
            )
            logger.info(
                "AIOrchestrator.success | client_id={client_id} response_len={length} attachments={count}",
                client_id=client_id,
                length=len(response_text),
                count=len(attachments),
            )
            return OrchestratorResult(text=response_text, media_attachments=attachments)
        except (
            InsufficientFundsError,
            WalletInsufficientFundsError,
            OrganizationSuspendedError,
            QuotaExceeded,
        ) as exc:
            logger.error(
                "LLM_REQUEST_FAILED | code={code} | client_id={client_id} | error={error}",
                code=getattr(exc, "code", None) or "INSUFFICIENT_FUNDS",
                client_id=client_id,
                error=str(exc),
            )
            return OrchestratorResult(text=await self._low_balance_reply(db_session, bot_id))
        except TransientLLMError as exc:
            if propagate_transient:
                raise
            logger.error(
                "AIOrchestrator.transient_llm_error | client_id={client_id} bot_id={bot_id} "
                "error={error}\n{traceback}",
                client_id=client_id,
                bot_id=bot_id,
                error=f"{type(exc).__name__}: {exc}",
                traceback=__import__("traceback").format_exc(),
            )
            logger.warning(
                "[LLM Fallback] Primary model failed with {error}, switching to fallback model",
                error=f"{type(exc).__name__}: {exc}",
            )
            try:
                recovered = await asyncio.wait_for(
                    self._try_emergency_provider_fallback(
                        db_session,
                        client_id=client_id,
                        current_node_data=current_node_data,
                        incoming_message=incoming_message,
                        bot_id=bot_id,
                        node_id=node_id,
                        channel=channel,
                    ),
                    timeout=float(getattr(settings, "LLM_FALLBACK_TIMEOUT_SECONDS", 25.0)),
                )
                if recovered is not None and (recovered.text or "").strip():
                    logger.info(
                        "[LLM Fallback] Fallback model succeeded | client_id={client_id} response_len={length}",
                        client_id=client_id,
                        length=len(recovered.text),
                    )
                    return recovered
            except asyncio.TimeoutError:
                logger.error(
                    "[LLM Fallback] Fallback model timed out | client_id={client_id}\n{traceback}",
                    client_id=client_id,
                    traceback=__import__("traceback").format_exc(),
                )
            except Exception as recovery_exc:
                logger.error(
                    "[LLM Fallback] Fallback model failed | error={error}\n{traceback}",
                    error=f"{type(recovery_exc).__name__}: {recovery_exc}",
                    traceback=__import__("traceback").format_exc(),
                )
            logger.error(
                "LLM_REQUEST_FAILED | code={code} | client_id={client_id} | error={error}\n{traceback}",
                code=diagnostic_log_service.classify_llm_failure_code(exc),
                client_id=client_id,
                error=str(exc),
                traceback=__import__("traceback").format_exc(),
            )
            return OrchestratorResult(text=self.FALLBACK_MESSAGE)
        except Exception as exc:
            logger.error(
                "LLM_REQUEST_FAILED | code={code} | client_id={client_id} | error={error}\n{traceback}",
                code=diagnostic_log_service.classify_llm_failure_code(exc),
                client_id=client_id,
                error=f"{type(exc).__name__}: {exc}",
                traceback=__import__("traceback").format_exc(),
            )
            logger.exception(
                "AIOrchestrator.failed | client_id={client_id} error={error}",
                client_id=client_id,
                error=str(exc),
            )
            if bot_id is not None:
                await self._log_ai_failure(
                    db_session,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    exc=exc,
                )
            return OrchestratorResult(text=self.FALLBACK_MESSAGE)

    async def generate_ai_response_with_trace(
        self,
        *,
        current_node_data: dict[str, Any],
        incoming_message: str,
        db_session: AsyncSession,
        client_id: uuid.UUID | None = None,
        history: list[dict[str, str]] | None = None,
        trace: ExecutionTraceBuilder | None = None,
        model_name: str | None = None,
        temperature: float | None = None,
        global_prompt: str | None = None,
        bot_id: uuid.UUID | None = None,
        node_id: str | None = None,
        channel: str | None = None,
        dry_run: bool = False,
    ) -> tuple[str, LLMMetricsTrace]:
        """Generate an AI reply and capture prompt, RAG, token, and cost diagnostics."""
        resolved_model = model_name or self.DEFAULT_FAST_MODEL
        resolved_temperature = 0.4 if temperature is None else float(temperature)
        node_prompt = str(current_node_data.get("prompt_context", "") or "").strip()
        resolved_global = global_prompt
        if not (resolved_global and str(resolved_global).strip()):
            resolved_global = await self._resolve_global_prompt(
                db_session,
                current_node_data,
                bot_id=bot_id,
            )
        merged_prompt = self._apply_platform_prompt_routing(
            self._merge_prompts(node_prompt, resolved_global),
            channel=channel,
        )

        try:
            if bot_id is not None and client_id is not None:
                await self._assert_sufficient_balance(db_session, bot_id, client_id, node_id=node_id)

            if history is not None:
                chat_history = list(history)
            elif client_id is not None:
                chat_history = await self._fetch_chat_history(db_session, client_id)
            else:
                chat_history = []
            rag_hits, rag_context = await self._fetch_rag_context_detailed(
                db_session,
                current_node_data,
                incoming_message,
                trace=trace,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
            )
            messages = self._build_llm_messages(
                system_prompt=merged_prompt,
                rag_context=rag_context,
                history=chat_history,
                incoming_message=incoming_message,
            )
            if bot_id is not None:
                from app.services.quota_service import QuotaExceeded, quota_service

                bot_row = await db_session.get(Bot, bot_id)
                if bot_row is not None:
                    try:
                        org_id = getattr(bot_row, "organization_id", None) or bot_row.user_id
                        await quota_service.assert_token_quota(db_session, org_id)
                    except QuotaExceeded:
                        raise
            completion = await self._request_completion_with_usage(
                messages,
                model_name=resolved_model,
                temperature=resolved_temperature,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                db=db_session,
                source="sandbox" if channel == "sandbox" else "orchestrator",
            )
            metrics = LLMMetricsTrace(
                model_name=completion.model_name or resolved_model,
                system_prompt=messages[0]["content"],
                user_query=incoming_message.strip(),
                raw_response=completion.text,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                total_tokens=completion.total_tokens,
                cost_kzt=(
                    0.0
                    if completion.cache_hit
                    else pricing_service.cost_usd_to_kzt(
                        pricing_service.calculate_cost(
                            completion.model_name or resolved_model,
                            completion.input_tokens,
                            completion.output_tokens,
                        )
                    )
                ),
                temperature=resolved_temperature,
                cache_hit=completion.cache_hit,
            )
            if trace is not None:
                trace.record_llm_metrics(metrics)
            if not completion.cache_hit and completion.total_tokens > 0 and bot_id is not None:
                await self._record_llm_usage_and_debit(
                    db_session,
                    bot_id=bot_id,
                    prompt_tokens=completion.input_tokens,
                    completion_tokens=completion.output_tokens,
                    model_name=completion.model_name or resolved_model,
                    billing_handled=completion.billing_handled,
                    client_id=client_id,
                    dry_run=dry_run,
                )
            return completion.text, metrics
        except (
            InsufficientFundsError,
            WalletInsufficientFundsError,
            OrganizationSuspendedError,
            QuotaExceeded,
        ):
            fallback = await self._low_balance_reply(db_session, bot_id)
            fallback_metrics = LLMMetricsTrace(
                model_name=resolved_model,
                system_prompt=merged_prompt or "You are a helpful support assistant.",
                user_query=incoming_message.strip(),
                raw_response=fallback,
                temperature=resolved_temperature,
            )
            if trace is not None:
                trace.record_error("insufficient_funds")
                trace.record_llm_metrics(fallback_metrics)
            return fallback, fallback_metrics
        except TransientLLMError as exc:
            logger.warning(
                "AIOrchestrator.trace_transient | error={error}\n{traceback}",
                error=str(exc),
                traceback=__import__("traceback").format_exc(),
            )
            if trace is not None:
                trace.record_error(str(exc))
            fallback_metrics = LLMMetricsTrace(
                model_name=resolved_model,
                system_prompt=merged_prompt or "You are a helpful support assistant.",
                user_query=incoming_message.strip(),
                raw_response=self.FALLBACK_MESSAGE,
                temperature=resolved_temperature,
            )
            if trace is not None:
                trace.record_llm_metrics(fallback_metrics)
            return self.FALLBACK_MESSAGE, fallback_metrics
        except Exception as exc:
            from app.services.llm.base import InsufficientCreditsForLLMError

            if isinstance(exc, InsufficientCreditsForLLMError):
                fallback_metrics = LLMMetricsTrace(
                    model_name=resolved_model,
                    system_prompt=merged_prompt or "You are a helpful support assistant.",
                    user_query=incoming_message.strip(),
                    raw_response=self.FUNDS_FALLBACK_MESSAGE,
                    temperature=resolved_temperature,
                )
                if trace is not None:
                    trace.record_error("insufficient_credits")
                    trace.record_llm_metrics(fallback_metrics)
                return self.FUNDS_FALLBACK_MESSAGE, fallback_metrics

            logger.error(
                "AIOrchestrator.trace_failed | error={error}\n{traceback}",
                error=f"{type(exc).__name__}: {exc}",
                traceback=__import__("traceback").format_exc(),
            )
            if trace is not None:
                trace.record_error(str(exc))
            if bot_id is not None:
                await self._log_ai_failure(
                    db_session,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    exc=exc,
                )
            fallback_metrics = LLMMetricsTrace(
                model_name=resolved_model,
                system_prompt=merged_prompt or "You are a helpful support assistant.",
                user_query=incoming_message.strip(),
                raw_response=self.FALLBACK_MESSAGE,
                temperature=resolved_temperature,
            )
            if trace is not None:
                trace.record_llm_metrics(fallback_metrics)
            return self.FALLBACK_MESSAGE, fallback_metrics

    async def _low_balance_reply(
        self, db_session: AsyncSession, bot_id: uuid.UUID | None
    ) -> str:
        if bot_id is not None:
            try:
                bot = await db_session.get(Bot, bot_id)
            except Exception:
                bot = None
            custom = getattr(bot, "low_balance_message", None) if bot is not None else None
            if isinstance(custom, str) and custom.strip():
                return custom.strip()
        return self.FUNDS_FALLBACK_MESSAGE

    async def _assert_sufficient_balance(
        self,
        db_session: AsyncSession,
        bot_id: uuid.UUID,
        client_id: uuid.UUID,
        *,
        node_id: str | None = None,
    ) -> None:
        if getattr(settings, "is_free_llm_route", False):
            return

        bot_result = await db_session.execute(select(Bot).where(Bot.id == bot_id))
        bot = bot_result.scalar_one_or_none()
        if bot is None:
            return

        org_id = getattr(bot, "organization_id", None)
        if org_id is not None:
            org = await db_session.get(Organization, org_id)
            if org is not None and bool(getattr(org, "is_suspended", False)):
                message = "Organization is suspended. Contact support to resume AI responses."
                await diagnostic_log_service.log(
                    db_session,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=DiagnosticErrorType.INSUFFICIENT_FUNDS,
                    error_message=message,
                    node_id=node_id,
                )
                raise OrganizationSuspendedError(message)

            from app.core.metrics import record_wallet_blocked
            from app.services.token_wallet_service import token_wallet_service

            token_check = await token_wallet_service.check_wallet_before_generation(
                db_session, org_id
            )
            if not token_check.allowed:
                record_wallet_blocked("precheck")
                message = (bot.low_balance_message or "").strip() or (
                    "Subscription balance depleted. Top up to resume AI responses."
                )
                await diagnostic_log_service.log(
                    db_session,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=DiagnosticErrorType.INSUFFICIENT_FUNDS,
                    error_message=message,
                    node_id=node_id,
                )
                raise InsufficientFundsError(message)

        subscription_result = await db_session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == bot.user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        subscription = subscription_result.scalar_one_or_none()
        if subscription is None:
            # Token wallet already passed (or org has no wallet gate); do not block on missing KZT plan.
            return

        if float(subscription.balance) > 0:
            return

        if org_id is not None:
            try:
                from app.services.billing.wallet_service import wallet_service as credit_wallet

                credit_balance = await credit_wallet.get_balance(db_session, org_id)
                if int(credit_balance) > 0:
                    return
            except Exception:
                pass
        # Token pre-check already allowed this org; skip KZT hard-fail.
        return

    async def _record_llm_usage_and_debit(
        self,
        db_session: AsyncSession,
        *,
        bot_id: uuid.UUID,
        prompt_tokens: int,
        completion_tokens: int,
        model_name: str,
        billing_handled: bool = False,
        client_id: uuid.UUID | None = None,
        dry_run: bool = False,
    ) -> None:
        """Persist LLMUsageLog (USD) and debit org wallet (credits or legacy KZT)."""
        from decimal import Decimal

        from app.core.metrics import LLM_REQUESTS, LLM_TOKENS
        from app.models.saas_metering import UsageMetricType
        from app.models.usage import LLMUsageLog
        from app.services.billing.wallet_service import WalletNotFoundError
        from app.services.llm.billing import charge_llm_credits, record_llm_usage_event
        from app.services.pricing_service import pricing_service
        from app.services.usage_service import usage_service

        bot = await db_session.get(Bot, bot_id)
        if bot is None:
            return

        org_id = getattr(bot, "organization_id", None)
        if org_id is None:
            from app.models.users import User

            owner = await db_session.get(User, bot.user_id)
            org_id = getattr(owner, "company_id", None) if owner is not None else None
        if org_id is None:
            logger.warning("AIOrchestrator.usage_skip_no_org | bot_id={bot_id}", bot_id=bot_id)
            return

        org = await db_session.get(Organization, org_id)
        if org is not None and bool(getattr(org, "is_suspended", False)):
            raise OrganizationSuspendedError("Organization is suspended.")

        cost_usd = pricing_service.calculate_cost(model_name, prompt_tokens, completion_tokens)
        provider = str(getattr(settings, "LLM_PROVIDER", "openai") or "openai").lower()
        if provider == "auto":
            provider = "openai"

        usage_log = LLMUsageLog(
            org_id=org_id,
            bot_id=bot_id,
            provider=provider[:64],
            model=str(model_name or "unknown")[:128],
            prompt_tokens=max(0, int(prompt_tokens)),
            completion_tokens=max(0, int(completion_tokens)),
            cost_usd=float(cost_usd),
        )
        db_session.add(usage_log)
        await db_session.flush()

        total_tokens = max(0, int(prompt_tokens) + int(completion_tokens))
        if not dry_run and total_tokens > 0:
            from app.services.token_wallet_service import token_wallet_service

            token_key = f"{client_id or bot_id}:{usage_log.id}"
            await token_wallet_service.debit_after_generation(
                db_session,
                org_id=org_id,
                amount_tokens=total_tokens,
                idempotency_key=token_key,
                bot_id=bot_id,
                conversation_id=client_id,
                model_used=str(model_name or "")[:100],
                metadata={"usage_log_id": str(usage_log.id), "source": "ai_orchestrator"},
            )

        if billing_handled or dry_run:
            logger.warning(
                "AIOrchestrator.dual_billing_skipped | bot_id={bot_id} "
                "reason={reason} usage_log={usage_log_id}",
                bot_id=bot_id,
                reason="dry_run" if dry_run else "billing_already_handled",
                usage_log_id=usage_log.id,
            )
            return

        reference_id = f"orchestrator-{usage_log.id}"

        try:
            from app.services.billing.wallet_service import wallet_service as credit_wallet
            from app.services.llm.base import InsufficientCreditsForLLMError

            await credit_wallet.get_balance(db_session, org_id)
            billing_meta = await charge_llm_credits(
                db_session,
                organization_id=org_id,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reference_id=reference_id,
            )
            await record_llm_usage_event(
                db_session,
                organization_id=org_id,
                user_id=bot.user_id,
                bot_id=bot_id,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                credits=int(billing_meta.get("credits") or 0),
                reference_id=reference_id,
                source="ai_orchestrator",
            )
        except WalletNotFoundError:
            cost_kzt = pricing_service.cost_usd_to_kzt(cost_usd)
            unit = Decimal(str(cost_kzt)) / Decimal(total_tokens) if total_tokens else Decimal("0")
            try:
                await usage_service.record_and_debit(
                    db_session,
                    user_id=bot.user_id,
                    organization_id=org_id,
                    bot_id=bot_id,
                    metric_type=UsageMetricType.LLM_TOKENS,
                    quantity=total_tokens or 1,
                    unit_cost=unit if total_tokens else Decimal(str(cost_kzt)),
                    meta={
                        "model": model_name,
                        "cost_usd": cost_usd,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "reference_id": reference_id,
                    },
                )
            except WalletInsufficientFundsError:
                raise
            except OrganizationSuspendedError:
                raise
            except Exception as exc:
                logger.warning("AIOrchestrator.usage_record_failed | error={error}", error=str(exc))
                raise
        except InsufficientCreditsForLLMError:
            raise
        except WalletInsufficientFundsError:
            raise
        except OrganizationSuspendedError:
            raise
        except Exception as exc:
            logger.warning("AIOrchestrator.usage_record_failed | error={error}", error=str(exc))
            raise

        LLM_TOKENS.labels(direction="total").inc(total_tokens)
        LLM_REQUESTS.labels(status="ok").inc()

    async def _log_ai_failure(
        self,
        db_session: AsyncSession,
        *,
        bot_id: uuid.UUID,
        client_id: uuid.UUID | None,
        node_id: str | None,
        exc: Exception,
    ) -> None:
        from app.services.llm.types import format_execution_failure_message

        error_type = DiagnosticErrorType.LLM_EXECUTION_FAILURE
        failure_code = "LLM_EXECUTION_FAILURE"
        try:
            failure_code = diagnostic_log_service.classify_llm_failure_code(exc)
            error_type = diagnostic_log_service.classify_llm_error(exc)
        except Exception:
            pass
        logger.error(
            "LLM_REQUEST_FAILED | code={code} | bot_id={bot_id} | error={error}",
            code=failure_code,
            bot_id=bot_id,
            error=str(exc),
        )
        if error_type != DiagnosticErrorType.LLM_EXECUTION_FAILURE:
            # Prefer explicit execution-failure records for exhausted LLM paths.
            if any(
                token in str(exc).lower()
                for token in ("timeout", "rate limit", "429", "503", "500", "overloaded")
            ):
                error_type = DiagnosticErrorType.LLM_EXECUTION_FAILURE

        message = format_execution_failure_message(provider_error=str(exc))
        try:
            await diagnostic_log_service.log(
                db_session,
                bot_id=bot_id,
                client_id=client_id,
                error_type=error_type,
                error_message=message,
                node_id=node_id,
            )
        except Exception as log_exc:
            logger.exception(
                "AIOrchestrator.diagnostic_log_failed | error={error}",
                error=str(log_exc),
            )

    @staticmethod
    def _merge_prompts(node_prompt: str, global_prompt: str | None) -> str:
        parts = [part.strip() for part in (global_prompt, node_prompt) if part and part.strip()]
        if not parts:
            return "You are a helpful support assistant."
        return "\n\n".join(parts)

    async def _resolve_global_prompt(
        self,
        db_session: AsyncSession,
        current_node_data: dict[str, Any],
        *,
        bot_id: uuid.UUID | None,
    ) -> str | None:
        """Agent «Промптинг» instructions, then node-carried global prompt."""
        from_node = str(
            current_node_data.get("global_prompt_instructions")
            or current_node_data.get("prompt_instructions")
            or ""
        ).strip()
        if from_node:
            return from_node
        if bot_id is None:
            return None
        bot = await db_session.get(Bot, bot_id)
        if bot is None:
            return None
        return str(getattr(bot, "prompt_instructions", "") or "").strip() or None

    @staticmethod
    def normalize_channel(channel: str | None, *, source: str | None = None) -> str:
        raw = (channel or source or "").strip().lower().replace(" ", "_")
        if raw in WHATSAPP_FAMILY or raw.startswith("whatsapp"):
            return "whatsapp"
        if raw in TELEGRAM_FAMILY or raw.startswith("telegram"):
            return "telegram"
        if raw in {"instagram", "ig"}:
            return "instagram"
        if raw in {"wazzup", "wz"}:
            return "wazzup"
        return raw or "unknown"

    @classmethod
    def _platform_micro_instructions(cls, channel: str | None) -> str | None:
        normalized = cls.normalize_channel(channel)
        if normalized == "whatsapp":
            return WHATSAPP_PROMPT_ADDON
        if normalized == "telegram":
            return TELEGRAM_PROMPT_ADDON
        return None

    @classmethod
    def _apply_platform_prompt_routing(cls, base_prompt: str, *, channel: str | None) -> str:
        addon = cls._platform_micro_instructions(channel)
        base = (base_prompt or "").strip() or "You are a helpful support assistant."
        if not addon:
            return base
        return f"{base}\n\n{addon}"

    @classmethod
    def _attachment_from_url(
        cls,
        url: str,
        *,
        hint: str | None = None,
        filename: str | None = None,
        source: str,
        similarity_score: float | None = None,
        caption: str | None = None,
    ) -> MediaAttachment | None:
        try:
            kind = infer_media_kind(url, hint=hint)
            return MediaAttachment(
                url=url,
                media_type=kind,
                filename=filename or filename_from_url(url),
                caption=caption,
                source=source,
                similarity_score=similarity_score,
            )
        except Exception as exc:
            logger.debug(
                "AIOrchestrator.skip_invalid_attachment | url={url} error={error}",
                url=url[:160],
                error=str(exc),
            )
            return None

    @classmethod
    def _collect_media_attachments(
        cls,
        *,
        rag_hits: list[RAGSearchHit],
        llm_text: str,
    ) -> list[MediaAttachment]:
        """Pull media URLs from high-relevance RAG metadata and LLM text hints."""
        collected: list[MediaAttachment] = []

        for hit in rag_hits:
            score = float(hit.get("similarity_score") or 0.0)
            metadata = hit.get("metadata") or {}
            urls = extract_urls_from_metadata(metadata if isinstance(metadata, dict) else {})

            # Also surface first-class TypedDict fields when present.
            for key in MEDIA_METADATA_KEYS:
                value = hit.get(key) if key in hit else None  # type: ignore[literal-required]
                if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
                    urls.append((value.strip(), "image" if "image" in key else None))

            if not urls:
                continue
            # Always keep media from highly relevant chunks; otherwise only when LLM asks for it.
            llm_wants_media = bool(LLM_MEDIA_HINT_PATTERN.search(llm_text or ""))
            if score < HIGH_RELEVANCE_THRESHOLD and not llm_wants_media:
                continue

            for url, hint in urls:
                attachment = cls._attachment_from_url(
                    url,
                    hint=hint,
                    filename=hit.get("file_name"),
                    source="rag",
                    similarity_score=score,
                )
                if attachment is not None:
                    collected.append(attachment)

        # Explicit URLs / markdown images in the model output.
        for match in URL_IN_TEXT_PATTERN.finditer(llm_text or ""):
            attachment = cls._attachment_from_url(
                match.group(1),
                source="llm_hint",
            )
            if attachment is not None:
                collected.append(attachment)

        for match in re.finditer(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)", llm_text or ""):
            attachment = cls._attachment_from_url(
                match.group(2),
                hint="image",
                source="llm_hint",
                caption=match.group(1) or None,
            )
            if attachment is not None:
                collected.append(attachment)

        return dedupe_attachments(collected)

    @staticmethod
    def _estimate_cost_kzt(model_name: str, total_tokens: int) -> float:
        rate = MODEL_COST_USD_PER_1K.get(model_name, 0.002)
        return round((total_tokens / 1000) * rate * USD_TO_KZT, 4)

    @staticmethod
    def _resolve_knowledge_base_id(
        current_node_data: dict[str, Any],
        bot_id: uuid.UUID | None,
    ) -> str | None:
        """
        Resolve the ChromaDB collection key for RAG.

        Knowledge documents are keyed by bot UUID. Flow nodes may leave
        ``knowledge_base_id`` empty or use a non-UUID preset label — in those
        cases fall back to the live bot id so production webhooks still query
        the active vector slice (``is_context_active`` filter applied downstream).
        """
        raw = str(current_node_data.get("knowledge_base_id") or "").strip()
        if raw:
            try:
                uuid.UUID(raw)
                return raw
            except ValueError:
                logger.debug(
                    "AIOrchestrator.kb_preset_fallback | preset={preset} bot_id={bot_id}",
                    preset=raw,
                    bot_id=bot_id,
                )
        if bot_id is not None:
            return str(bot_id)
        return None

    @staticmethod
    def _hits_to_trace(hits: list[RAGSearchHit]) -> list[RAGChunkTrace]:
        return [
            RAGChunkTrace(
                text=str(hit["text"]),
                similarity_score=float(hit["similarity_score"]),
                document_id=hit.get("document_id"),
                file_name=hit.get("file_name"),
                chunk_index=hit.get("chunk_index"),
            )
            for hit in hits
        ]

    async def _fetch_rag_context_detailed(
        self,
        db_session: AsyncSession,
        current_node_data: dict[str, Any],
        incoming_message: str,
        *,
        trace: ExecutionTraceBuilder | None = None,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
    ) -> tuple[list[RAGSearchHit], list[str]]:
        knowledge_base_id = self._resolve_knowledge_base_id(current_node_data, bot_id)
        if not knowledge_base_id:
            logger.debug("AIOrchestrator.rag_skipped | reason=no_knowledge_base_id")
            return [], []

        try:
            bot_uuid = uuid.UUID(knowledge_base_id)
        except ValueError:
            logger.warning(
                "AIOrchestrator.rag_skipped | reason=invalid_knowledge_base_id value={value}",
                value=knowledge_base_id,
            )
            return [], []

        try:
            activation = await knowledge_base_service.get_activation_snapshot(
                db_session, bot_uuid
            )
        except Exception as exc:
            logger.warning(
                "AIOrchestrator.rag_snapshot_failed | kb_id={kb_id} error={error}",
                kb_id=knowledge_base_id,
                error=str(exc),
            )
            return [], []
        inactive_document_ids = list(activation.inactive_document_ids)
        # Zero active documents → skip Chroma entirely (avoids empty $in/$nin errors).
        if not activation.active_document_ids:
            logger.info(
                "AIOrchestrator.rag_skipped | knowledge_base_id={kb_id} reason=no_active_documents inactive={inactive}",
                kb_id=knowledge_base_id,
                inactive=len(inactive_document_ids),
            )
            return [], []

        try:
            from app.core.embeddings import embedding_api_keys_available

            if not embedding_api_keys_available():
                logger.warning(
                    "AIOrchestrator.rag_skipped | kb_id={kb_id} reason=missing_embedding_api_key "
                    "— continuing without RAG",
                    kb_id=knowledge_base_id,
                )
                return [], []

            hits = await search_knowledge_base(
                knowledge_base_id=knowledge_base_id,
                query=incoming_message,
                top_k=settings.RAG_TOP_K,
                excluded_document_ids=inactive_document_ids,
            )
        except Exception as exc:
            logger.error(
                "AIOrchestrator.rag_search_failed | kb_id={kb_id} error={error}\n{traceback}",
                kb_id=knowledge_base_id,
                error=f"{type(exc).__name__}: {exc}",
                traceback=__import__("traceback").format_exc(),
            )
            return [], []
        if not hits and bot_id is not None:
            await diagnostic_log_service.log(
                db_session,
                bot_id=bot_id,
                client_id=client_id,
                error_type=DiagnosticErrorType.RAG_EMPTY,
                error_message="Knowledge base query returned no matching chunks.",
                node_id=node_id,
            )
        trace_chunks = self._hits_to_trace(hits)
        if trace is not None:
            trace.record_rag_chunks(trace_chunks)
        return hits, [str(hit["text"]) for hit in hits if hit.get("text")]

    async def _fetch_chat_history(
        self,
        db_session: AsyncSession,
        client_id: uuid.UUID,
    ) -> list[dict[str, str]]:
        limit = settings.MAX_CHAT_HISTORY_MESSAGES
        result = await db_session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.client_id == client_id,
                ChatMessage.sender.in_([MessageSender.CLIENT, MessageSender.BOT]),
                ~ChatMessage.message_text.like("[System]%"),
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        rows = list(reversed(result.scalars().all()))

        if not rows:
            logger.debug(
                "AIOrchestrator.empty_history | client_id={client_id}",
                client_id=client_id,
            )
            return []

        history: list[dict[str, str]] = []
        for row in rows:
            role = self._map_sender_to_role(row.sender)
            content = (row.message_text or "").strip()
            if not content:
                continue
            history.append({"role": role, "content": content})

        logger.debug(
            "AIOrchestrator.history_loaded | client_id={client_id} messages={count}",
            client_id=client_id,
            count=len(history),
        )
        return history

    async def _fetch_rag_context(
        self,
        db_session: AsyncSession,
        current_node_data: dict[str, Any],
        incoming_message: str,
        *,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
    ) -> list[str]:
        knowledge_base_id = self._resolve_knowledge_base_id(current_node_data, bot_id)
        if not knowledge_base_id:
            logger.debug("AIOrchestrator.rag_skipped | reason=no_knowledge_base_id")
            return []

        try:
            bot_uuid = uuid.UUID(knowledge_base_id)
        except ValueError:
            logger.warning(
                "AIOrchestrator.rag_skipped | reason=invalid_knowledge_base_id value={value}",
                value=knowledge_base_id,
            )
            return []

        activation = await knowledge_base_service.get_activation_snapshot(db_session, bot_uuid)
        inactive_document_ids = list(activation.inactive_document_ids)
        if not activation.active_document_ids:
            logger.info(
                "AIOrchestrator.rag_skipped | knowledge_base_id={kb_id} reason=no_active_documents inactive={inactive}",
                kb_id=knowledge_base_id,
                inactive=len(inactive_document_ids),
            )
            return []

        try:
            from app.core.embeddings import embedding_api_keys_available

            if not embedding_api_keys_available():
                logger.warning(
                    "AIOrchestrator.rag_skipped | kb_id={kb_id} reason=missing_embedding_api_key "
                    "— continuing without RAG",
                    kb_id=knowledge_base_id,
                )
                return []
            chunks = await search_knowledge_base(
                knowledge_base_id=knowledge_base_id,
                query=incoming_message,
                top_k=settings.RAG_TOP_K,
                excluded_document_ids=inactive_document_ids,
            )
        except Exception as exc:
            logger.error(
                "AIOrchestrator.rag_search_failed | kb_id={kb_id} error={error}\n{traceback}",
                kb_id=knowledge_base_id,
                error=f"{type(exc).__name__}: {exc}",
                traceback=__import__("traceback").format_exc(),
            )
            return []
        chunk_texts = [str(hit["text"]) for hit in chunks if hit.get("text")]
        if not chunk_texts:
            logger.info(
                "AIOrchestrator.rag_empty | knowledge_base_id={kb_id}",
                kb_id=knowledge_base_id,
            )
            if bot_id is not None:
                await diagnostic_log_service.log(
                    db_session,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=DiagnosticErrorType.RAG_EMPTY,
                    error_message="Knowledge base query returned no matching chunks.",
                    node_id=node_id,
                )
            return []

        logger.info(
            "AIOrchestrator.rag_loaded | knowledge_base_id={kb_id} chunks={count} excluded_inactive={excluded}",
            kb_id=knowledge_base_id,
            count=len(chunk_texts),
            excluded=len(inactive_document_ids),
        )
        return chunk_texts

    def _build_llm_messages(
        self,
        system_prompt: str,
        rag_context: list[str],
        history: list[dict[str, str]],
        incoming_message: str,
    ) -> list[dict[str, str]]:
        system_parts = [system_prompt.strip() or "You are a helpful support assistant."]

        from app.services.rag.prompt_context import build_rag_system_addon

        system_parts.append(build_rag_system_addon(rag_context))

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._truncate("\n\n".join(system_parts))},
        ]
        messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": self._truncate(incoming_message.strip() or "Hello"),
            }
        )
        return self._truncate_messages(messages)

    async def _try_emergency_provider_fallback(
        self,
        db: AsyncSession,
        *,
        client_id: uuid.UUID,
        current_node_data: dict[str, Any],
        incoming_message: str,
        bot_id: uuid.UUID | None,
        node_id: str | None,
        channel: str | None,
    ) -> OrchestratorResult | None:
        """
        Last-chance recovery after primary TransientLLMError (429/503/timeout).

        Forces the configured ``FALLBACK_LLM_PROVIDER`` (Groq) / ``OPENAI_FALLBACK_MODEL``
        so the user does not immediately get the overload stub.
        """
        from app.services.llm.client import OpenAIChatClient
        from app.services.llm_orchestrator import llm_orchestrator

        history = await self._fetch_chat_history(db, client_id)
        global_prompt = await self._resolve_global_prompt(
            db,
            current_node_data,
            bot_id=bot_id,
        )
        system_prompt = self._apply_platform_prompt_routing(
            self._merge_prompts(
                str(current_node_data.get("prompt_context", "") or ""),
                global_prompt,
            ),
            channel=channel,
        )
        messages = self._build_llm_messages(
            system_prompt=system_prompt,
            rag_context=[],
            history=history,
            incoming_message=incoming_message,
        )

        fallback_model, fallback_key, fallback_base = llm_orchestrator._resolve_fallback_endpoint()
        if not fallback_model:
            return None

        logger.warning(
            "[LLM Fallback] Primary model failed with transient error, switching to fallback model {model}",
            model=fallback_model,
        )
        client = OpenAIChatClient(
            timeout_seconds=float(getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 45.0))
        )
        completion = await client.chat_completion(
            messages=messages,
            model=fallback_model,
            temperature=float(current_node_data.get("temperature") or 0.4),
            api_key=fallback_key,
            base_url=fallback_base,
        )
        text = (completion.text or "").strip()
        if not text:
            return None
        return OrchestratorResult(text=text, media_attachments=[])

    async def _gateway_completion_with_usage(
        self,
        db: AsyncSession,
        messages: list[dict[str, str]],
        *,
        organization_id: uuid.UUID,
        model_name: str,
        temperature: float,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
        source: str = "orchestrator",
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMCompletionResult:
        from app.services.internal_llm_service import complete_via_gateway
        from app.services.llm.base import InsufficientCreditsForLLMError
        from app.services.llm.types import LLMCompletion
        from app.services.llm_orchestrator import llm_orchestrator

        try:
            response = await complete_via_gateway(
                db,
                organization_id,
                messages,
                model_name=model_name,
                temperature=temperature,
                bot_id=bot_id,
                source=source,
                tools=tools,
            )
        except InsufficientCreditsForLLMError as exc:
            raise InsufficientFundsError(str(exc)) from exc

        text = (response.content or "").strip()
        tools_executed: list[str] = []
        booking_ok = False

        # Gateway returns tool_calls with empty content — execute tools and get a user reply.
        if response.tool_calls and bot_id is not None:
            interim = LLMCompletion(
                text=text,
                model=response.model_name or model_name,
                input_tokens=response.prompt_tokens,
                output_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                tool_calls=list(response.tool_calls),
            )
            resolved = await llm_orchestrator._resolve_tool_calls(
                interim,
                messages=list(messages),
                model=response.model_name or model_name,
                temperature=temperature,
                tools=tools,
                bot_id=bot_id,
                client_id=client_id,
                db=db,
            )
            text = (resolved.text or "").strip()
            tools_executed = list(getattr(resolved, "tools_executed", None) or [])
            booking_ok = bool(getattr(resolved, "booking_tools_succeeded", False))
            if not tools_executed and response.tool_calls:
                for tc in response.tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
                    name = str((fn or {}).get("name") if fn else tc.get("name") or "")
                    if name:
                        tools_executed.append(name)

        if not text and (
            booking_ok or any(name in self.BOOKING_TOOL_NAMES for name in tools_executed)
        ):
            text = self.TOOL_SUCCESS_CONFIRMATION_MESSAGE
            booking_ok = True

        return LLMCompletionResult(
            text=text,
            input_tokens=response.prompt_tokens,
            output_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            model_name=response.model_name or model_name,
            billing_handled=True,
            tools_executed=tools_executed,
            booking_tools_succeeded=booking_ok,
        )

    async def _request_completion(
        self,
        messages: list[dict[str, str]],
        *,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
        db: AsyncSession | None = None,
        source: str = "orchestrator",
    ) -> str:
        result = await self._request_completion_with_usage(
            messages,
            bot_id=bot_id,
            client_id=client_id,
            node_id=node_id,
            db=db,
            source=source,
        )
        return result.text

    async def _request_completion_with_usage(
        self,
        messages: list[dict[str, str]],
        *,
        model_name: str | None = None,
        temperature: float | None = None,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
        db: AsyncSession | None = None,
        source: str = "orchestrator",
    ) -> LLMCompletionResult:
        provider = settings.LLM_PROVIDER.lower()
        resolved_model = model_name or self.DEFAULT_FAST_MODEL
        resolved_temperature = 0.4 if temperature is None else float(temperature)

        system_prompt = ""
        incoming_text = ""
        for message in messages:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "system" and not system_prompt:
                system_prompt = content
            if role == "user":
                incoming_text = content

        # Exact-match Redis short-circuit before provider round-trips.
        cached = await llm_response_cache.get_cached_response(
            bot_id=bot_id,
            system_prompt=system_prompt,
            incoming_text=incoming_text,
            model_name=resolved_model,
            temperature=resolved_temperature,
        )
        if cached is None:
            # Optional semantic stub — no-op until embedding registry is enabled.
            cached = await llm_response_cache.get_semantic_cached_response(
                bot_id=bot_id,
                incoming_text=incoming_text,
            )

        if cached is not None:
            logger.info(
                "AIOrchestrator.cache_hit | bot_id={bot_id} client_id={client_id} "
                "node_id={node_id} response_len={length}",
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                length=len(cached.text),
            )
            return LLMCompletionResult(
                text=cached.text,
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                total_tokens=cached.total_tokens,
                cache_hit=True,
                model_name=cached.model_name or resolved_model,
            )

        logger.debug(
            "AIOrchestrator.cache_miss | bot_id={bot_id} model={model} source={source}",
            bot_id=bot_id,
            model=resolved_model,
            source=source,
        )

        openai_tools: list[dict[str, Any]] | None = None
        if db is not None and bot_id is not None:
            from app.services.bot_workspace_config import openai_tools_for_bot

            bot = await db.get(Bot, bot_id)
            if bot is not None:
                mapped = openai_tools_for_bot(bot)
                openai_tools = mapped or None

        completion: LLMCompletionResult | None = None

        if db is not None and bot_id is not None:
            from app.services.internal_llm_service import resolve_bot_organization_id

            org_id = await resolve_bot_organization_id(db, bot_id)
            if org_id is not None:
                try:
                    completion = await self._gateway_completion_with_usage(
                        db,
                        messages,
                        organization_id=org_id,
                        model_name=resolved_model,
                        temperature=resolved_temperature,
                        bot_id=bot_id,
                        client_id=client_id,
                        node_id=node_id,
                        source=source,
                        tools=openai_tools,
                    )
                except InsufficientFundsError:
                    raise
                except Exception as exc:
                    logger.error(
                        "LLM_REQUEST_FAILED | code={code} | bot_id={bot_id} | error={error}\n{traceback}",
                        code=diagnostic_log_service.classify_llm_failure_code(exc),
                        bot_id=bot_id,
                        error=f"{type(exc).__name__}: {exc}",
                        traceback=__import__("traceback").format_exc(),
                    )
                    # Fall through to platform settings.OPENAI_API_KEY path below.

        if completion is None and provider in {"auto", "openai", "openrouter", "groq"} and (
            settings.OPENAI_API_KEY
            or getattr(settings, "OPENROUTER_API_KEY", None)
            or getattr(settings, "GROQ_API_KEY", None)
        ):
            try:
                completion = await self._openai_completion(
                    messages,
                    model_name=resolved_model,
                    temperature=resolved_temperature,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    tools=openai_tools,
                    db=db,
                )
            except TransientLLMError as exc:
                logger.warning(
                    "[LLM Fallback] Primary model failed with {error}, switching to fallback model",
                    error=f"{type(exc).__name__}: {exc}",
                )
                from app.services.llm_orchestrator import llm_orchestrator

                fb_model, fb_key, fb_base = llm_orchestrator._resolve_fallback_endpoint()
                if fb_model and fb_model != resolved_model:
                    try:
                        from app.services.llm.client import OpenAIChatClient

                        client = OpenAIChatClient()
                        fb_result = await client.chat_completion(
                            messages=messages,
                            model=fb_model,
                            temperature=resolved_temperature,
                            tools=openai_tools,
                            api_key=fb_key,
                            base_url=fb_base,
                        )
                        if fb_result.tool_calls and bot_id is not None:
                            fb_result = await llm_orchestrator._resolve_tool_calls(
                                fb_result,
                                messages=messages,
                                model=fb_model,
                                temperature=resolved_temperature,
                                tools=openai_tools,
                                bot_id=bot_id,
                                client_id=client_id,
                                db=db,
                            )
                        from app.services.llm.tool_reply_sanitize import sanitize_outbound_text

                        completion = LLMCompletionResult(
                            text=sanitize_outbound_text(
                                fb_result.text,
                                tools_executed=list(
                                    getattr(fb_result, "tools_executed", None) or []
                                ),
                                booking_ok=bool(
                                    getattr(fb_result, "booking_tools_succeeded", False)
                                ),
                            ),
                            input_tokens=fb_result.input_tokens,
                            output_tokens=fb_result.output_tokens,
                            total_tokens=fb_result.total_tokens,
                            model_name=fb_result.model or fb_model,
                            tools_executed=list(
                                getattr(fb_result, "tools_executed", None) or []
                            ),
                            booking_tools_succeeded=bool(
                                getattr(fb_result, "booking_tools_succeeded", False)
                            ),
                        )
                        logger.info(
                            "[LLM Fallback] Fallback model succeeded | primary={primary} fallback={fallback}",
                            primary=resolved_model,
                            fallback=fb_model,
                        )
                    except Exception as fb_exc:
                        logger.error(
                            "[LLM Fallback] Fallback model failed | error={error}",
                            error=str(fb_exc),
                        )
                        if provider in {"openai", "openrouter", "groq"}:
                            raise exc from fb_exc
                elif provider in {"openai", "openrouter", "groq"}:
                    raise
            except Exception as exc:
                logger.error(
                    "LLM_REQUEST_FAILED | code={code} | error={error}\n{traceback}",
                    code=diagnostic_log_service.classify_llm_failure_code(exc),
                    error=f"{type(exc).__name__}: {exc}",
                    traceback=__import__("traceback").format_exc(),
                )
                # Transient failures are retried by Celery / fallback chain — avoid noisy vault spam.
                if bot_id is not None and not isinstance(exc, TransientLLMError):
                    diagnostic_log_service.schedule_log(
                        bot_id=bot_id,
                        client_id=client_id,
                        error_type=diagnostic_log_service.classify_llm_error(exc),
                        error_message=str(exc),
                        node_id=node_id,
                    )
                if provider in {"openai", "openrouter", "groq"}:
                    raise

        if completion is None and provider in {"auto", "ollama"}:
            try:
                completion = await self._ollama_completion(
                    messages,
                    model_name=settings.OLLAMA_MODEL,
                    temperature=resolved_temperature,
                )
            except Exception as exc:
                logger.warning(
                    "AIOrchestrator.ollama_failed | error={error}",
                    error=str(exc),
                )
                if provider == "ollama":
                    raise

        if completion is None:
            raise RuntimeError("No LLM provider is configured or available")

        # Persist for subsequent identical turns (non-blocking on Redis errors).
        await llm_response_cache.set_cached_response(
            bot_id=bot_id,
            system_prompt=system_prompt,
            incoming_text=incoming_text,
            response_text=completion.text,
            model_name=completion.model_name or resolved_model,
            temperature=resolved_temperature,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            total_tokens=completion.total_tokens,
        )
        await llm_response_cache.register_semantic_turn(
            bot_id=bot_id,
            incoming_text=incoming_text,
            response_text=completion.text,
        )
        return completion

    async def _openai_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model_name: str | None = None,
        temperature: float = 0.4,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        db: AsyncSession | None = None,
    ) -> LLMCompletionResult:
        from app.services.llm_orchestrator import llm_orchestrator

        result = await llm_orchestrator.complete(
            messages,
            model=model_name,
            temperature=temperature,
            bot_id=bot_id,
            client_id=client_id,
            node_id=node_id,
            db=db,
            tools=tools,
            degrade_on_exhaustion=False,
        )
        text = (result.text or "").strip()
        tools_executed = list(getattr(result, "tools_executed", None) or [])
        booking_ok = bool(getattr(result, "booking_tools_succeeded", False))
        if not text and (
            booking_ok or any(name in self.BOOKING_TOOL_NAMES for name in tools_executed)
        ):
            text = self.TOOL_SUCCESS_CONFIRMATION_MESSAGE
            booking_ok = True
        return LLMCompletionResult(
            text=text,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            model_name=result.model,
            tools_executed=tools_executed,
            booking_tools_succeeded=booking_ok,
        )

    async def _ollama_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model_name: str | None = None,
        temperature: float = 0.4,
    ) -> LLMCompletionResult:
        url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        resolved_model = model_name or settings.OLLAMA_MODEL
        payload = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        logger.debug(
            "AIOrchestrator.ollama_request | model={model} messages={count}",
            model=resolved_model,
            count=len(messages),
        )

        async with httpx.AsyncClient(timeout=settings.OLLAMA_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data.get("message", {}).get("content")
        if not content:
            raise RuntimeError("Ollama returned an empty completion")

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        output_tokens = int(data.get("eval_count") or 0)
        if prompt_tokens == 0 and output_tokens == 0:
            joined = "\n".join(message["content"] for message in messages)
            estimated = max(1, len(joined) // 4)
            prompt_tokens = estimated
            output_tokens = max(1, len(str(content)) // 4)

        total_tokens = prompt_tokens + output_tokens
        return LLMCompletionResult(
            text=str(content).strip(),
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            model_name=resolved_model,
        )

    @staticmethod
    def _map_sender_to_role(sender: MessageSender) -> str:
        if sender == MessageSender.CLIENT:
            return "user"
        if sender == MessageSender.OPERATOR:
            return "assistant"
        return "assistant"

    @staticmethod
    def _truncate(text: str, max_chars: int | None = None) -> str:
        limit = max_chars or settings.MAX_PROMPT_CHARS
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _truncate_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        total_chars = sum(len(message["content"]) for message in messages)
        if total_chars <= settings.MAX_PROMPT_CHARS:
            return messages

        system_message = messages[0]
        remaining = settings.MAX_PROMPT_CHARS - len(system_message["content"])
        trimmed: list[dict[str, str]] = [system_message]

        tail = messages[1:]
        for message in reversed(tail):
            content = message["content"]
            if len(content) <= remaining:
                trimmed.insert(1, message)
                remaining -= len(content)
            elif remaining > 0:
                trimmed.insert(1, {**message, "content": self._truncate(content, remaining)})
                break
            else:
                break

        logger.warning(
            "AIOrchestrator.prompt_truncated | original_messages={original} kept={kept}",
            original=len(messages),
            kept=len(trimmed),
        )
        return trimmed
