"""LLM node — PromptTemplate + ResilientLLMGateway with billing."""



from __future__ import annotations



import json

import uuid

from typing import Any, Protocol



from loguru import logger



from app.services.flow.engine import FlowEngineError

from app.services.flow.nodes.base import (

    BaseNodeHandler,

    NodeExecutionContext,

    NodeHandlerResult,

)

from app.services.llm.pricing import normalize_model_name





class _LLMGatewayProto(Protocol):

    async def complete_for_organization(self, *args: Any, **kwargs: Any) -> Any: ...





class LLMNodeHandler(BaseNodeHandler):

    node_types = ("llm", "ai", "gpt", "ai_agent", "aiagent")



    def __init__(

        self,

        *,

        gateway: _LLMGatewayProto | None = None,

        prompt_service: Any | None = None,

    ) -> None:

        self._gateway = gateway

        self._prompt_service = prompt_service



    def _prompts(self) -> Any:

        if self._prompt_service is not None:

            return self._prompt_service

        from app.services.llm.prompt_service import prompt_template_service



        return prompt_template_service



    def _gateway_client(self) -> _LLMGatewayProto:

        if self._gateway is not None:

            return self._gateway

        from app.services.llm.factory import get_llm_gateway



        return get_llm_gateway(include_unconfigured=True)



    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:

        data = ctx.data

        output_var = str(data.get("output_variable") or "llm_response")

        system_prompt = await self._resolve_prompt(ctx)

        user_text = str(

            data.get("user_message")

            or ctx.variables.get("message_text")

            or ctx.variables.get("last_input")

            or ctx.variables.get("message")

            or ""

        )

        user_text = ctx.interpolate(user_text)



        messages = self._build_messages(ctx, system_prompt, user_text)



        org_id = ctx.organization_id

        if org_id is None:

            raw_org = ctx.variables.get("organization_id")

            if raw_org:

                org_id = uuid.UUID(str(raw_org))



        if ctx.db is None or org_id is None:

            raise FlowEngineError(

                "LLM node requires db + organization_id for billed completion."

            )



        temperature = float(data.get("temperature", 0.7))

        max_tokens = int(data.get("max_tokens", 1000))

        model_name = self._resolve_model_name(data)

        reference_id = str(

            data.get("reference_id")

            or f"flow-{ctx.session.session_id}-{ctx.node_id}"

        )



        gateway = self._gateway_client()

        gateway_kwargs: dict[str, Any] = {}

        if model_name:

            gateway_kwargs["model"] = model_name



        response = await gateway.complete_for_organization(

            ctx.db,

            org_id,

            messages,

            temperature=temperature,

            max_tokens=max_tokens,

            reference_id=reference_id,

            **gateway_kwargs,

        )

        content = getattr(response, "content", None) or str(response)

        prompt_tokens = int(getattr(response, "prompt_tokens", 0) or 0)

        completion_tokens = int(getattr(response, "completion_tokens", 0) or 0)

        resolved_model = getattr(response, "model_name", None) or model_name



        ctx.variables[output_var] = content

        ctx.variables["llm_response"] = content

        ctx.variables["llm_model_name"] = resolved_model

        ctx.variables["llm_prompt_tokens"] = prompt_tokens

        ctx.variables["llm_completion_tokens"] = completion_tokens

        ctx.variables["llm_total_tokens"] = prompt_tokens + completion_tokens



        billing = {}

        raw = getattr(response, "raw", None)

        if isinstance(raw, dict):

            billing = raw.get("billing") or {}



        logger.info(

            "Flow.LLM.done | session={sid} node={node} model={model} "

            "prompt_tokens={pt} completion_tokens={ct} credits={credits}",

            sid=ctx.session.session_id,

            node=ctx.node_id,

            model=resolved_model,

            pt=prompt_tokens,

            ct=completion_tokens,

            credits=(billing or {}).get("credits"),

        )

        return NodeHandlerResult(

            event="llm",

            output={

                "text": content,

                "output_variable": output_var,

                "billing": billing,

                "model_name": resolved_model,

                "prompt_tokens": prompt_tokens,

                "completion_tokens": completion_tokens,

                "total_tokens": prompt_tokens + completion_tokens,

            },

        )



    def _resolve_model_name(self, data: dict[str, Any]) -> str | None:

        for key in ("model_name", "llm_model_name", "model"):

            value = data.get(key)

            if value and str(value).strip():

                return normalize_model_name(str(value))

        return None



    def _build_messages(

        self,

        ctx: NodeExecutionContext,

        system_prompt: str,

        user_text: str,

    ) -> list[dict[str, str]]:

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]



        rag_chunks = ctx.variables.get("rag_chunks")
        rag_context = ctx.variables.get("rag_context")
        if isinstance(rag_chunks, list) and rag_chunks:
            from app.services.rag.prompt_context import build_rag_system_addon

            rag_block = build_rag_system_addon([str(chunk) for chunk in rag_chunks if str(chunk).strip()])
        elif rag_context and str(rag_context).strip():
            from app.services.rag.prompt_context import build_rag_system_addon

            rag_block = build_rag_system_addon(
                [part.strip() for part in str(rag_context).split("\n\n") if part.strip()]
            )
        else:
            rag_block = ""

        if rag_block:
            messages.append({"role": "system", "content": ctx.interpolate(rag_block)})



        for item in self._resolve_history(ctx):

            messages.append(item)



        messages.append({"role": "user", "content": user_text or " "})

        return messages



    def _resolve_history(self, ctx: NodeExecutionContext) -> list[dict[str, str]]:

        data = ctx.data

        raw = data.get("messages") or data.get("message_history")

        if raw is None:

            for key in ("message_history", "chat_history", "messages"):

                raw = ctx.variables.get(key)

                if raw:

                    break



        if not raw:

            return []



        if isinstance(raw, str):

            try:

                parsed = json.loads(raw)

                raw = parsed if isinstance(parsed, list) else []

            except json.JSONDecodeError:

                return []



        if not isinstance(raw, list):

            return []



        history: list[dict[str, str]] = []

        for item in raw:

            if not isinstance(item, dict):

                continue

            role = str(item.get("role") or "").strip().lower()

            content = item.get("content")

            if role not in {"user", "assistant", "system"} or content is None:

                continue

            history.append(

                {

                    "role": role,

                    "content": ctx.interpolate(str(content)),

                }

            )

        return history



    async def _resolve_prompt(self, ctx: NodeExecutionContext) -> str:

        data = ctx.data

        inline = (

            data.get("prompt_context")

            or data.get("prompt")

            or data.get("system_prompt")

            or data.get("content")

        )

        if inline:

            prompt = ctx.interpolate(str(inline))

        else:

            template_name = data.get("prompt_template") or data.get("template_name")

            template_id = data.get("prompt_template_id") or data.get("template_id")

            if template_name or template_id:

                if ctx.db is None or ctx.organization_id is None:

                    raise FlowEngineError(

                        "LLM node prompt template lookup requires db + organization_id."

                    )

                prompts = self._prompts()

                rendered = await prompts.render_template(

                    ctx.db,

                    ctx.organization_id,

                    dict(ctx.variables),

                    template_id=uuid.UUID(str(template_id)) if template_id else None,

                    name=str(template_name) if template_name else None,

                )

                prompt = str(rendered.get("rendered") or "")

            else:

                prompt = ctx.interpolate(

                    str(

                        ctx.variables.get("message_text")

                        or "You are a helpful assistant."

                    )

                )



        modifier = data.get("prompt_modifier")

        if modifier and str(modifier).strip():

            prompt = f"{prompt.rstrip()}\n\n{ctx.interpolate(str(modifier).strip())}"

        return prompt


