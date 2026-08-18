"""Resilient LLM Gateway — fallback chain + per-provider circuit breakers + billing."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.services.llm.base import (
    BaseLLMProvider,
    InsufficientCreditsForLLMError,
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from app.services.llm.billing import charge_llm_credits, record_llm_usage_event
from app.services.llm.circuit_breaker import CircuitBreaker
from app.services.llm.pricing import (
    estimate_request_credits,
    normalize_model_name,
    resolve_provider_for_model,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.billing.wallet_service import WalletService


def _provider_model_name(provider: BaseLLMProvider, model_hint: Any = None) -> str:
    if model_hint:
        return str(model_hint)
    return str(getattr(provider, "model", None) or getattr(provider, "model_name", None) or "unknown")


def _sentry_fallback_breadcrumb(*, primary: str, secondary: str) -> None:
    """Record cascade Primary → Secondary switch in the Sentry breadcrumb trail."""
    try:
        import sentry_sdk

        sentry_sdk.add_breadcrumb(
            category="llm_gateway",
            message=f"Fallback triggered from {primary} to {secondary}",
            level="warning",
            data={"primary": primary, "secondary": secondary},
        )
    except Exception:  # noqa: BLE001 — telemetry must never break completions
        pass


def _sentry_circuit_open_alert(
    *,
    provider_id: str,
    model_name: str,
    error: BaseException | None,
) -> None:
    """Emit a structured outage event when a provider circuit breaker trips OPEN."""
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("alert_type", "llm_provider_outage")
            scope.set_tag("provider", provider_id)
            scope.set_tag("model", model_name)
            scope.set_extra("last_error", str(error) if error is not None else "")
            sentry_sdk.capture_message(
                f"🚨 LLM Provider Down: {provider_id} ({model_name}) — Circuit Breaker OPEN",
                level="error",
            )
    except Exception:  # noqa: BLE001
        pass


class LLMGatewayError(LLMProviderError):
    """All providers in the fallback chain failed (or were circuit-open)."""

    def __init__(
        self,
        message: str,
        *,
        failures: list[BaseException] | None = None,
        attempted: list[str] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        last = failures[-1] if failures else cause
        provider = getattr(last, "provider", None) if last is not None else None
        status = getattr(last, "status_code", None) if last is not None else None
        super().__init__(
            message,
            provider=provider if isinstance(provider, str) else None,
            status_code=status if isinstance(status, int) else None,
            cause=cause or last,
        )
        self.failures = list(failures or [])
        self.attempted = list(attempted or [])


class ResilientLLMGateway:
    """
    Provider-agnostic completion with ordered fallback + circuit breakers.

    Optional org billing via ``complete_for_organization`` — preflight balance
    check, then idempotent ``WalletService.deduct_credits`` after success.
    """

    def __init__(
        self,
        providers: list[BaseLLMProvider],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
        wallet_service: WalletService | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ResilientLLMGateway requires at least one provider.")
        self.providers = list(providers)
        self._wallet_service = wallet_service
        self._failure_threshold = int(failure_threshold)
        self._recovery_timeout = float(recovery_timeout)
        self._breakers: dict[str, CircuitBreaker] = dict(circuit_breakers or {})
        for provider in self.providers:
            key = self._provider_key(provider)
            if key not in self._breakers:
                self._breakers[key] = CircuitBreaker(
                    failure_threshold=self._failure_threshold,
                    recovery_timeout=self._recovery_timeout,
                    name=key,
                )

    def breaker_for(self, provider: BaseLLMProvider | str) -> CircuitBreaker:
        key = provider if isinstance(provider, str) else self._provider_key(provider)
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
                name=key,
            )
        return self._breakers[key]

    def _wallet(self) -> WalletService:
        if self._wallet_service is not None:
            return self._wallet_service
        from app.services.billing.wallet_service import wallet_service

        return wallet_service

    @staticmethod
    def _provider_key(provider: BaseLLMProvider) -> str:
        """
        Stable breaker identity across org-chain rebuilds.

        Same vendor + base_url + default model share one breaker so OPEN state
        persists between ``complete_for_organization`` calls.
        """
        base = str(getattr(provider, "provider_id", None) or type(provider).__name__)
        base_url = str(getattr(provider, "base_url", None) or "").rstrip("/")
        model = str(getattr(provider, "model", None) or "")
        return f"{base}|{base_url}|{model}"

    def _breaker_for_provider(self, provider: BaseLLMProvider) -> CircuitBreaker:
        key = self._provider_key(provider)
        breaker = self._breakers.get(key)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
                name=key,
            )
            self._breakers[key] = breaker
        return breaker

    def _resolve_model_hint(self, **kwargs: Any) -> str:
        explicit = kwargs.get("model")
        if explicit:
            return normalize_model_name(str(explicit))
        for provider in self.providers:
            model = getattr(provider, "model", None)
            if model:
                return normalize_model_name(str(model))
        return "gpt-4o-mini"

    def _ordered_providers(self, *, model: str | None) -> list[BaseLLMProvider]:
        """Prefer the vendor that owns ``model``; keep remaining as fallback."""
        if not model:
            return self._promote_fallback(list(self.providers), after=1)
        preferred_id = resolve_provider_for_model(model)
        preferred: list[BaseLLMProvider] = []
        others: list[BaseLLMProvider] = []
        for provider in self.providers:
            pid = getattr(provider, "provider_id", None) or type(provider).__name__
            if str(pid).lower() == preferred_id:
                preferred.append(provider)
            else:
                others.append(provider)
        if not preferred:
            logger.debug(
                "LLMGateway.no_preferred_provider | model={model} preferred={preferred} "
                "— using default chain order",
                model=model,
                preferred=preferred_id,
            )
            return self._promote_fallback(list(self.providers), after=1)
        return self._promote_fallback(preferred + others, after=len(preferred))

    @staticmethod
    def _promote_fallback(
        providers: list[BaseLLMProvider],
        *,
        after: int,
    ) -> list[BaseLLMProvider]:
        """
        Move ``FALLBACK_LLM_PROVIDER`` directly behind the primary providers.

        DB-registry chains are ordered by the model table, so without this the
        first retry after an OpenRouter outage could land on a paid model instead
        of the configured free fallback. Keyless providers are left in place —
        promoting one would only add a guaranteed auth failure to the hot path.
        """
        from app.core.config import settings

        wanted_id = str(getattr(settings, "FALLBACK_LLM_PROVIDER", "") or "").strip().lower()
        if not wanted_id or wanted_id in {"auto"} or after >= len(providers):
            return providers

        wanted_model = str(getattr(settings, "FALLBACK_LLM_MODEL", "") or "").strip().lower()
        chosen: int | None = None
        for index in range(after, len(providers)):
            provider = providers[index]
            pid = str(
                getattr(provider, "provider_id", None) or type(provider).__name__
            ).strip().lower()
            if pid != wanted_id or not getattr(provider, "api_key", None):
                continue
            if chosen is None:
                chosen = index
            if wanted_model and str(getattr(provider, "model", "") or "").lower() == wanted_model:
                chosen = index
                break

        if chosen is None or chosen == after:
            return providers
        return (
            providers[:after]
            + [providers[chosen]]
            + [p for i, p in enumerate(providers) if i >= after and i != chosen]
        )

    def effective_chain(self, *, model: str | None = None) -> list[BaseLLMProvider]:
        """Provider order this gateway would use for ``model`` (diagnostics)."""
        return self._ordered_providers(model=model)

    @staticmethod
    def _provider_owns_model(provider: BaseLLMProvider, model: str) -> bool:
        """True when ``model`` is servable by this vendor."""
        pid = str(
            getattr(provider, "provider_id", None) or type(provider).__name__
        ).strip().lower()
        own_model = str(getattr(provider, "model", "") or "").strip().lower()
        candidate = model.strip().lower()
        if own_model and own_model == candidate:
            return True
        return resolve_provider_for_model(candidate) == pid

    def _kwargs_for_provider(
        self,
        provider: BaseLLMProvider,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Drop a foreign ``model`` hint before retrying on another vendor.

        Groq cannot serve ``openai/gpt-oss-20b:free`` — forwarding the primary's
        model id would turn every fallback into a 404 instead of an answer. Only
        applied to fallback attempts; the first provider always gets the hint as-is.
        """
        call_kwargs = dict(kwargs)
        model_hint = call_kwargs.get("model")
        if not model_hint:
            return call_kwargs
        if self._provider_owns_model(provider, str(model_hint)):
            return call_kwargs

        call_kwargs.pop("model", None)
        logger.debug(
            "LLMGateway.model_remapped | provider={provider} requested={requested} "
            "using={using}",
            provider=getattr(provider, "provider_id", type(provider).__name__),
            requested=model_hint,
            using=getattr(provider, "model", None),
        )
        return call_kwargs

    @staticmethod
    def _announce_fallback(
        providers: list[BaseLLMProvider],
        index: int,
        error: BaseException,
    ) -> None:
        """Warn + breadcrumb when the chain advances to the next vendor."""
        if index + 1 >= len(providers):
            return
        primary = str(
            getattr(providers[index], "provider_id", type(providers[index]).__name__)
        )
        secondary = str(
            getattr(
                providers[index + 1],
                "provider_id",
                type(providers[index + 1]).__name__,
            )
        )
        logger.warning(
            "LLM.fallback_triggered | Primary failed: {error} -> Switching to {secondary}",
            error=f"{type(error).__name__}: {error}",
            secondary=secondary,
        )
        _sentry_fallback_breadcrumb(primary=primary, secondary=secondary)

    async def _ensure_credits_available(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        required: int,
    ) -> int:
        """Preflight: block empty / underfunded wallets before any vendor round-trip."""
        from app.services.billing.wallet_service import (
            InsufficientFundsError,
            WalletNotFoundError,
        )

        wallet = self._wallet()
        try:
            balance = await wallet.get_balance(db, organization_id)
        except WalletNotFoundError:
            await wallet.get_or_create_wallet(db, organization_id, initial_balance=0)
            balance = 0

        if required > 0 and balance < required:
            raise InsufficientCreditsForLLMError(
                f"Insufficient credits for LLM request: balance={balance}, "
                f"required>={required} (org={organization_id}).",
                organization_id=organization_id,
                balance=balance,
                required=required,
            )
        return balance

    async def _deduct_and_meter(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        response: LLMResponse,
        reference_id: str,
        user_id: uuid.UUID | None,
        bot_id: uuid.UUID | None,
    ) -> LLMResponse:
        if response.billing_handled:
            logger.warning(
                "LLMGateway.dual_billing_skipped | org={org} ref={ref} "
                "reason=billing_already_handled",
                org=organization_id,
                ref=reference_id,
            )
            return response

        billing_meta = await charge_llm_credits(
            db,
            organization_id=organization_id,
            model_name=response.model_name,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            reference_id=reference_id,
            wallet_service=self._wallet(),
        )

        await record_llm_usage_event(
            db,
            organization_id=organization_id,
            user_id=user_id,
            bot_id=bot_id,
            model_name=response.model_name,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            credits=int(billing_meta.get("credits") or 0),
            reference_id=reference_id,
            source="llm_gateway",
        )

        await self._write_llm_usage_log(
            db,
            organization_id=organization_id,
            bot_id=bot_id,
            response=response,
            credits=int(billing_meta.get("credits") or 0),
        )

        response.billing_handled = True
        response.raw = {
            **(response.raw or {}),
            "billing": billing_meta,
            "billing_handled": True,
            "provider": response.provider,
        }
        return response

    async def _write_llm_usage_log(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        bot_id: uuid.UUID | None,
        response: LLMResponse,
        credits: int,
    ) -> None:
        """Persist provider-accurate ``LLMUsageLog`` for the model that answered."""
        try:
            from app.models.usage import LLMUsageLog
            from app.services.llm.pricing import resolve_provider_for_model
            from app.services.pricing_service import pricing_service

            provider = (
                (response.provider or "").strip()
                or resolve_provider_for_model(response.model_name)
                or "openai"
            )
            cost_usd = float(
                pricing_service.calculate_cost(
                    response.model_name,
                    response.prompt_tokens,
                    response.completion_tokens,
                )
            )
            # Prefer credit-derived USD when pricing_service yields 0 for custom models.
            if cost_usd <= 0 and credits > 0:
                cost_usd = float(credits) * 0.001

            db.add(
                LLMUsageLog(
                    org_id=organization_id,
                    bot_id=bot_id,
                    provider=provider[:64],
                    model=str(response.model_name or "unknown")[:128],
                    prompt_tokens=max(0, int(response.prompt_tokens)),
                    completion_tokens=max(0, int(response.completion_tokens)),
                    cost_usd=cost_usd,
                )
            )
            await db.flush()
        except Exception as exc:
            logger.warning(
                "LLMGateway.usage_log_failed | org={org} model={model} error={error}",
                org=organization_id,
                model=response.model_name,
                error=str(exc),
            )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        failures: list[BaseException] = []
        attempted: list[str] = []
        skipped_open: list[str] = []
        model_hint = kwargs.get("model")
        providers = self._ordered_providers(
            model=str(model_hint) if model_hint else None,
        )

        for index, provider in enumerate(providers):
            label = str(getattr(provider, "provider_id", type(provider).__name__))
            breaker = self._breaker_for_provider(provider)

            if not breaker.allow_request():
                skipped_open.append(label)
                logger.warning(
                    "LLMGateway.circuit_open | provider={provider} index={index} — skipping",
                    provider=label,
                    index=index,
                )
                continue

            attempted.append(label)
            call_kwargs = (
                dict(kwargs) if index == 0 else self._kwargs_for_provider(provider, kwargs)
            )
            model_name = _provider_model_name(provider, call_kwargs.get("model"))
            try:
                response = await provider.complete(
                    messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **call_kwargs,
                )
            except LLMAuthenticationError as exc:
                # Permanent credential failures must not trip the circuit breaker.
                failures.append(exc)
                logger.error(
                    "LLMGateway.auth_failed | provider={provider} index={index} error={error}",
                    provider=label,
                    index=index,
                    error=str(exc),
                )
                self._announce_fallback(providers, index, exc)
                continue
            except (
                LLMRateLimitError,
                LLMTimeoutError,
                LLMInvalidResponseError,
                LLMProviderError,
            ) as exc:
                opened = breaker.record_failure()
                failures.append(exc)
                logger.warning(
                    "LLMGateway.provider_failed | provider={provider} index={index} "
                    "error={error} state={state} — trying next",
                    provider=label,
                    index=index,
                    error=str(exc),
                    state=breaker.state.value,
                )
                if opened:
                    _sentry_circuit_open_alert(
                        provider_id=label,
                        model_name=model_name,
                        error=exc,
                    )
                self._announce_fallback(providers, index, exc)
                continue
            except Exception as exc:
                # Unexpected errors still trip the breaker and advance the chain.
                opened = breaker.record_failure()
                wrapped = LLMProviderError(
                    str(exc) or "Unexpected provider failure.",
                    provider=label if isinstance(label, str) else None,
                    cause=exc,
                )
                failures.append(wrapped)
                logger.exception(
                    "LLMGateway.provider_unexpected | provider={provider} index={index}",
                    provider=label,
                    index=index,
                )
                if opened:
                    _sentry_circuit_open_alert(
                        provider_id=label,
                        model_name=model_name,
                        error=exc,
                    )
                self._announce_fallback(providers, index, exc)
                continue

            breaker.record_success()
            if not response.provider:
                response.provider = label
            if index > 0 or skipped_open:
                logger.info(
                    "LLMGateway.fallback_success | provider={provider} index={index} "
                    "attempted={attempted}",
                    provider=label,
                    index=index,
                    attempted=attempted,
                )
            return response

        parts = [f"{type(f).__name__}: {f}" for f in failures]
        if skipped_open and not failures:
            detail = f"all providers circuit-open: {', '.join(skipped_open)}"
        elif skipped_open:
            detail = (
                f"failures=[{'; '.join(parts)}]; "
                f"circuit-open skipped=[{', '.join(skipped_open)}]"
            )
        else:
            detail = "; ".join(parts) or "no providers available"

        raise LLMGatewayError(
            f"All LLM providers failed. {detail}",
            failures=failures,
            attempted=attempted,
            cause=failures[-1] if failures else None,
        )

    async def complete_for_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        *,
        reference_id: str | None = None,
        user_id: uuid.UUID | None = None,
        bot_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Resilient completion + credit billing for a tenant.

        1. Preflight credit check (blocks vendor call when underfunded).
        2. Provider chain via ``complete``.
        3. Idempotent ``deduct_credits`` keyed by ``reference_id``.
        4. Optional ``UsageEvent`` (LLM_TOKENS) without legacy KZT debit.
        """
        ref = (reference_id or "").strip() or str(uuid.uuid4())
        model_hint = self._resolve_model_hint(**kwargs)
        estimated = estimate_request_credits(model_hint, messages, max_tokens)

        await self._ensure_credits_available(
            db,
            organization_id,
            required=estimated,
        )

        use_org_providers = bool(kwargs.pop("use_org_providers", True))
        runner: ResilientLLMGateway = self
        if use_org_providers:
            try:
                from app.services.llm.factory import (
                    build_gateway_providers_for_organization,
                )

                org_providers = await build_gateway_providers_for_organization(
                    db,
                    organization_id,
                    include_unconfigured=True,
                )
                if org_providers:
                    # Share breaker map so OPEN state survives org-chain rebuilds.
                    runner = ResilientLLMGateway(
                        org_providers,
                        failure_threshold=self._failure_threshold,
                        recovery_timeout=self._recovery_timeout,
                        circuit_breakers=self._breakers,
                        wallet_service=self._wallet(),
                    )
            except Exception as exc:
                logger.warning(
                    "LLMGateway.org_providers_unavailable | org={org} error={error} "
                    "— using injected provider chain",
                    org=organization_id,
                    error=str(exc),
                )
                runner = self

        response = await runner.complete(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return await self._deduct_and_meter(
            db,
            organization_id=organization_id,
            response=response,
            reference_id=ref,
            user_id=user_id,
            bot_id=bot_id,
        )


# Short alias preferred by call sites.
LLMGateway = ResilientLLMGateway
