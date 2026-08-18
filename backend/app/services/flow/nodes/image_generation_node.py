"""Image generation flow node — Jinja2 prompt + credit billing + media providers."""

from __future__ import annotations

import uuid
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError
from loguru import logger

from app.services.billing.wallet_service import InsufficientFundsError
from app.services.flow.engine import FlowEngineError
from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
)
from app.services.media.base_media import (
    MediaGenerationError,
    MediaGenerationRequest,
    MediaRegistry,
    aspect_ratio_to_dimensions,
)
from app.services.media.pricing import IMAGE_TX_TYPE, calculate_image_credits


class ImageGenerationNodeHandler(BaseNodeHandler):
    node_types = ("image_generation",)

    def __init__(self, *, registry: type[MediaRegistry] | None = None) -> None:
        self._registry = registry or MediaRegistry

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        data = ctx.data
        provider = str(data.get("provider") or "kling").strip().lower()
        if provider in {"nano_banana", "nano-banana-pro", "nano_banana_pro"}:
            provider = "nanobanana"

        model_name = str(data.get("model_name") or "").strip() or None
        aspect_ratio = str(data.get("aspect_ratio") or "1:1").strip()
        result_variable = str(data.get("result_variable") or "generated_image_url").strip()
        negative_prompt = str(data.get("negative_prompt") or "").strip() or None
        prompt_template = str(
            data.get("prompt_template") or data.get("prompt") or ""
        ).strip()
        if not prompt_template:
            raise FlowEngineError("image_generation node requires prompt_template.")

        org_id = ctx.organization_id
        if org_id is None:
            raw_org = ctx.variables.get("organization_id")
            if raw_org:
                org_id = uuid.UUID(str(raw_org))
        if ctx.db is None or org_id is None:
            raise FlowEngineError(
                "image_generation node requires db + organization_id for billing."
            )

        prompt = self._render_prompt_template(prompt_template, ctx.variables)
        width, height = aspect_ratio_to_dimensions(aspect_ratio)
        explicit_width = data.get("width")
        explicit_height = data.get("height")
        if explicit_width and explicit_height:
            width = int(explicit_width)
            height = int(explicit_height)

        credits = calculate_image_credits(provider, model_name)
        reference_id = str(
            data.get("reference_id")
            or f"flow-image-{ctx.session.session_id}-{ctx.node_id}"
        )

        from app.services.billing.wallet_service import wallet_service

        try:
            deduct = await wallet_service.deduct_credits(
                ctx.db,
                org_id,
                credits,
                IMAGE_TX_TYPE,
                reference_id=reference_id,
            )
        except InsufficientFundsError as exc:
            raise FlowEngineError(
                f"Insufficient credits for image generation: balance={exc.balance}, "
                f"required={exc.required or credits}."
            ) from exc

        request = MediaGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            model_name=model_name,
        )

        try:
            connector = self._registry.get_connector(provider)
            result = await connector.generate_image(request)
        except MediaGenerationError as exc:
            logger.error(
                "Flow.image_generation.failed | session={sid} node={node} provider={provider} error={error}",
                sid=ctx.session.session_id,
                node=ctx.node_id,
                provider=provider,
                error=str(exc),
            )
            raise FlowEngineError(str(exc)) from exc

        ctx.variables[result_variable] = result.url
        ctx.variables["generated_image_url"] = result.url

        billing = {
            "credits": credits,
            "reference_id": reference_id,
            "idempotent_replay": deduct.idempotent_replay,
            "balance_after": deduct.balance_after,
            "transaction_id": str(deduct.transaction_id) if deduct.transaction_id else None,
        }

        logger.info(
            "Flow.image_generation.done | session={sid} node={node} provider={provider} credits={credits}",
            sid=ctx.session.session_id,
            node=ctx.node_id,
            provider=provider,
            credits=credits,
        )
        return NodeHandlerResult(
            event="image_generation",
            output={
                "url": result.url,
                "result_variable": result_variable,
                "provider": result.provider,
                "revised_prompt": result.revised_prompt,
                "billing": billing,
                "model_name": model_name,
            },
        )

    @staticmethod
    def _render_prompt_template(template: str, variables: dict[str, Any]) -> str:
        env = Environment(undefined=StrictUndefined, autoescape=False)
        context = {
            "session": {"variables": variables},
            **variables,
        }
        try:
            rendered = env.from_string(template).render(**context)
        except (TemplateSyntaxError, UndefinedError) as exc:
            raise FlowEngineError(f"Invalid prompt_template: {exc}") from exc
        rendered = str(rendered).strip()
        if not rendered:
            raise FlowEngineError("prompt_template rendered to an empty string.")
        return rendered
