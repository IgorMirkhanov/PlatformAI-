"""CRUD and connection tests for dynamic LLM models."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.llm_model import LLMModel
from app.schemas.llm_models import (
    LLMModelCreate,
    LLMModelListResponse,
    LLMModelRead,
    LLMModelTestConnectionRequest,
    LLMModelTestConnectionResponse,
    LLMModelUpdate,
)
from app.services.llm.base import LLMAuthenticationError, LLMProviderError
from app.services.llm_model_registry import (
    CachedLLMModel,
    ensure_model_cache,
    invalidate_model_cache,
    refresh_model_cache_from_db,
)


class LLMModelServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class LLMModelService:
    async def list_models(
        self,
        db: AsyncSession,
        *,
        provider: str | None = None,
        active_only: bool = True,
    ) -> LLMModelListResponse:
        await ensure_model_cache(db)

        stmt = select(LLMModel).order_by(LLMModel.provider.asc(), LLMModel.display_name.asc())
        if active_only:
            stmt = stmt.where(LLMModel.is_active.is_(True))
        if provider:
            stmt = stmt.where(LLMModel.provider == provider.strip().lower())

        rows = (await db.execute(stmt)).scalars().all()
        items = [LLMModelRead.model_validate(row) for row in rows]
        return LLMModelListResponse(items=items, total=len(items))

    async def create_model(self, db: AsyncSession, payload: LLMModelCreate) -> LLMModelRead:
        existing = await db.scalar(
            select(LLMModel).where(
                LLMModel.provider == payload.provider,
                LLMModel.model_name == payload.model_name,
            )
        )
        if existing is not None:
            raise LLMModelServiceError(
                "Model with this provider and model_name already exists.",
                status_code=409,
            )

        if payload.is_system_default:
            await self._clear_system_default(db)

        row = LLMModel(
            provider=payload.provider.strip().lower(),
            model_name=payload.model_name.strip(),
            display_name=payload.display_name.strip(),
            base_url=payload.base_url,
            context_window=payload.context_window,
            cost_per_1k_input=payload.cost_per_1k_input,
            cost_per_1k_output=payload.cost_per_1k_output,
            is_active=payload.is_active,
            is_system_default=payload.is_system_default,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        invalidate_model_cache()
        await refresh_model_cache_from_db(db)
        return LLMModelRead.model_validate(row)

    async def update_model(
        self,
        db: AsyncSession,
        model_id: uuid.UUID,
        payload: LLMModelUpdate,
    ) -> LLMModelRead:
        row = await db.get(LLMModel, model_id)
        if row is None:
            raise LLMModelServiceError("LLM model not found.", status_code=404)

        data = payload.model_dump(exclude_unset=True)
        if "provider" in data and data["provider"] is not None:
            data["provider"] = str(data["provider"]).strip().lower()
        if "model_name" in data and data["model_name"] is not None:
            data["model_name"] = str(data["model_name"]).strip()

        new_provider = data.get("provider", row.provider)
        new_model_name = data.get("model_name", row.model_name)
        if (new_provider, new_model_name) != (row.provider, row.model_name):
            conflict = await db.scalar(
                select(LLMModel).where(
                    LLMModel.provider == new_provider,
                    LLMModel.model_name == new_model_name,
                    LLMModel.id != model_id,
                )
            )
            if conflict is not None:
                raise LLMModelServiceError(
                    "Another model already uses this provider and model_name.",
                    status_code=409,
                )

        if data.get("is_system_default"):
            await self._clear_system_default(db)

        for key, value in data.items():
            setattr(row, key, value)

        await db.flush()
        await db.refresh(row)
        invalidate_model_cache()
        await refresh_model_cache_from_db(db)
        return LLMModelRead.model_validate(row)

    async def deactivate_model(self, db: AsyncSession, model_id: uuid.UUID) -> LLMModelRead:
        row = await db.get(LLMModel, model_id)
        if row is None:
            raise LLMModelServiceError("LLM model not found.", status_code=404)
        row.is_active = False
        await db.flush()
        await db.refresh(row)
        invalidate_model_cache()
        await refresh_model_cache_from_db(db)
        return LLMModelRead.model_validate(row)

    async def test_connection(
        self,
        db: AsyncSession,
        payload: LLMModelTestConnectionRequest,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> LLMModelTestConnectionResponse:
        provider = payload.provider.strip().lower()
        model_name = payload.model_name.strip()
        base_url = payload.base_url
        api_key = payload.api_key

        if payload.model_id is not None:
            row = await db.get(LLMModel, payload.model_id)
            if row is None:
                raise LLMModelServiceError("LLM model not found.", status_code=404)
            provider = row.provider
            model_name = row.model_name
            base_url = row.base_url
            cfg = CachedLLMModel.from_row(row)
        else:
            cfg = CachedLLMModel(
                id="test",
                provider=provider,
                model_name=model_name,
                display_name=model_name,
                base_url=base_url,
                context_window=128_000,
                cost_per_1k_input=Decimal("0"),
                cost_per_1k_output=Decimal("0"),
                is_active=True,
                is_system_default=False,
            )

        if api_key is None and organization_id is not None:
            from app.services.ai_keys_service import ai_keys_service

            org_keys = await ai_keys_service.get_active_keys_map(db, organization_id)
            api_key = org_keys.get(provider) or org_keys.get("openai")

        if api_key is None:
            api_key = self._resolve_platform_api_key(provider)

        provider_instance = self.instantiate_provider(
            cfg,
            api_key=api_key,
        )

        messages = [{"role": "user", "content": "Reply with the single word: pong"}]
        t0 = time.perf_counter()
        try:
            response = await provider_instance.complete(
                messages=messages,
                max_tokens=8,
                temperature=0.0,
                model=model_name,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
            snippet = (response.content or "").strip()[:120]
            return LLMModelTestConnectionResponse(
                ok=True,
                latency_ms=round(latency_ms, 2),
                model=model_name,
                provider=provider,
                message="Connection successful.",
                sample_reply=snippet or None,
            )
        except LLMAuthenticationError as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return LLMModelTestConnectionResponse(
                ok=False,
                latency_ms=round(latency_ms, 2),
                model=model_name,
                provider=provider,
                message=f"Authentication failed: {exc}",
            )
        except LLMProviderError as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return LLMModelTestConnectionResponse(
                ok=False,
                latency_ms=round(latency_ms, 2),
                model=model_name,
                provider=provider,
                message=str(exc),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.warning("LLMModel.test_connection_failed | error={error}", error=str(exc))
            return LLMModelTestConnectionResponse(
                ok=False,
                latency_ms=round(latency_ms, 2),
                model=model_name,
                provider=provider,
                message=str(exc),
            )

    def instantiate_provider(
        self,
        cfg: CachedLLMModel,
        *,
        api_key: str | None = None,
    ) -> Any:
        import app.services.llm.providers  # noqa: F401
        from app.services.llm.factory import LLMProviderFactory
        from app.services.llm.providers.openai_provider import OpenAIProvider

        provider_id = cfg.provider
        openai_compatible = provider_id in {
            "custom_openai",
            "openrouter",
            "vllm",
            "ollama",
        } or bool(cfg.base_url)

        if openai_compatible:
            resolved_base = cfg.base_url or getattr(settings, "OLLAMA_BASE_URL", None)
            if provider_id == "ollama" and resolved_base and not resolved_base.endswith("/v1"):
                resolved_base = f"{resolved_base.rstrip('/')}/v1"
            # Self-hosted endpoints accept any bearer; real vendors must not get a
            # placeholder key — that turns a missing key into an opaque 401.
            local_endpoint = provider_id in {"ollama", "vllm", "custom_openai"}
            return OpenAIProvider(
                api_key=api_key or ("ollama" if local_endpoint else None),
                model=cfg.model_name,
                base_url=resolved_base,
                provider_id=provider_id,
            )

        kwargs: dict[str, Any] = {"model": cfg.model_name}
        if api_key:
            kwargs["api_key"] = api_key
        return LLMProviderFactory.create(provider_id, **kwargs)

    def build_dynamic_providers(
        self,
        models: list[CachedLLMModel],
        *,
        org_api_keys: dict[str, str] | None = None,
    ) -> list[Any]:
        org_keys = org_api_keys or {}
        providers: list[Any] = []
        seen: set[tuple[str, str, str | None]] = set()

        for cfg in models:
            if not cfg.is_active:
                continue
            signature = (cfg.provider, cfg.model_name, cfg.base_url)
            if signature in seen:
                continue
            seen.add(signature)
            key = org_keys.get(cfg.provider) or self._resolve_platform_api_key(cfg.provider)
            try:
                providers.append(self.instantiate_provider(cfg, api_key=key))
            except Exception as exc:
                logger.debug(
                    "LLMModel.dynamic_provider_skip | model={model} error={error}",
                    model=cfg.model_name,
                    error=str(exc),
                )
        return providers

    @staticmethod
    def _resolve_platform_api_key(provider: str) -> str | None:
        mapping = {
            "openai": settings.OPENAI_API_KEY,
            "groq": settings.GROQ_API_KEY,
            "anthropic": settings.ANTHROPIC_API_KEY,
            "gemini": settings.GEMINI_API_KEY,
            "deepseek": settings.DEEPSEEK_API_KEY,
            "glm": settings.GLM_API_KEY,
            "qwen": settings.QWEN_API_KEY,
            "ollama": "ollama",
            "custom_openai": settings.OPENAI_API_KEY,
            "openrouter": settings.OPENAI_API_KEY,
            "vllm": settings.OPENAI_API_KEY,
        }
        return mapping.get(provider)

    async def _clear_system_default(self, db: AsyncSession) -> None:
        rows = (await db.execute(select(LLMModel).where(LLMModel.is_system_default.is_(True)))).scalars()
        for row in rows:
            row.is_system_default = False


llm_model_service = LLMModelService()
