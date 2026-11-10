"""LLM orchestration — timeouts, primary→fallback chain, graceful degradation."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core_models import DiagnosticErrorType
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.llm.client import OpenAIChatClient
from app.services.llm.types import (
    SAFE_USER_FALLBACK_MESSAGE,
    LLMCompletion,
    TransientLLMError,
    format_execution_failure_message,
)

WaitIntent = Literal["calc", "photo", "both", "wait", "none"]

_WAIT_PATTERN = re.compile(
    r"(?i)("
    r"подожд(?:ите|и)|сейчас\s+(?:отправ|расчит|выполн)|"
    r"выполню\s+расч[её]т|отправлю\s+(?:вам\s+)?(?:фото|файл|изображен)|"
    r"please\s+wait|i(?:'| a)m\s+(?:sending|calculating)"
    r")"
)
_CALC_INTENT_PATTERN = re.compile(
    r"(?i)("
    r"расч[её]т|рассчит|калькуляц|стоимост|смет[аыу]|itemization|"
    r"calculate|quot(?:e|ation)|estimate|pricing"
    r")"
)
_PHOTO_INTENT_PATTERN = re.compile(
    r"(?i)("
    r"фото|изображен|картинк|образц|файл|галере|каталог|"
    r"photo|image|sample|file|catalog|gallery"
    r")"
)
_CALC_RESULT_PATTERN = re.compile(
    r"(?i)("
    r"₸|тенге|итого|предварительн\w*\s+стоимост|"
    r"TOTAL_|PIECES\s*=|ONE_SIDE_COST|DOUBLE-?SIDED\s+COST"
    r")"
)
_MEDIA_TOOL_PATTERN = re.compile(
    r"(?i)(фото|изображен|картинк|образц|файл|photo|image|sample|file|catalog|gallery|цвет)"
)
_CALC_TOOL_PATTERN = re.compile(
    r"(?i)(расч[её]т|рассчит|calc|quote|estimate|pricing|cost|price|смет)"
)
_CALC_NUDGE = (
    "Не обещай «подождите» и не вызывай tools. Сейчас же выведи клиенту полный "
    "расчёт на русском с итоговой суммой. Сохраняй дробные значения точно "
    "(высота 3,5 м → 3.5, никогда не округляй до 3). Если каких-то параметров "
    "не хватает — коротко переспроси, но не откладывай расчёт на потом."
)


class LLMOrchestrator:
    """
    Execute chat completions with a strict client timeout and one-shot fallback.

    Primary model (node selection or ``OPENAI_CHAT_MODEL``, default gpt-4o) →
    on 429 / 5xx / timeout → retry once on ``OPENAI_FALLBACK_MODEL`` (gpt-4o-mini).
    """

    SAFE_FALLBACK_MESSAGE = SAFE_USER_FALLBACK_MESSAGE

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 20.0)
        )
        self.fallback_model = (
            fallback_model
            or getattr(settings, "OPENAI_FALLBACK_MODEL", None)
            or "gpt-4o-mini"
        )
        self._client = OpenAIChatClient(timeout_seconds=self.timeout_seconds)

    def resolve_primary_model(self, model_name: str | None = None) -> str:
        return (model_name or settings.OPENAI_CHAT_MODEL or "gpt-4o").strip() or "gpt-4o"

    def _resolve_fallback_endpoint(self) -> tuple[str, str | None, str | None]:
        """
        Pick a real alternate vendor for 429/503/timeout recovery.

        Prefer Groq (``FALLBACK_LLM_*``) so we do not retry the same OpenRouter
        free pool with a different model id.
        """
        fallback_provider = str(getattr(settings, "FALLBACK_LLM_PROVIDER", "") or "").strip().lower()
        fallback_model = (
            str(getattr(settings, "FALLBACK_LLM_MODEL", "") or "").strip()
            or self.fallback_model
            or "gpt-4o-mini"
        )
        if fallback_provider == "groq" and getattr(settings, "GROQ_API_KEY", None):
            return (
                fallback_model or str(getattr(settings, "GROQ_CHAT_MODEL", "") or "openai/gpt-oss-20b"),
                str(settings.GROQ_API_KEY),
                str(getattr(settings, "GROQ_BASE_URL", None) or "https://api.groq.com/openai/v1"),
            )
        # Paid OpenAI path when a non-OpenRouter key is configured.
        openai_key = (settings.OPENAI_API_KEY or "").strip()
        openrouter_key = str(getattr(settings, "OPENROUTER_API_KEY", None) or "").strip()
        if openai_key and openai_key != openrouter_key and not openai_key.startswith("sk-or-"):
            return (self.fallback_model or "gpt-4o-mini", openai_key, None)
        if getattr(settings, "GROQ_API_KEY", None):
            return (
                str(getattr(settings, "GROQ_CHAT_MODEL", None) or fallback_model),
                str(settings.GROQ_API_KEY),
                str(getattr(settings, "GROQ_BASE_URL", None) or "https://api.groq.com/openai/v1"),
            )
        return (fallback_model, None, None)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.4,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
        db: AsyncSession | None = None,
        tools: list[dict[str, Any]] | None = None,
        degrade_on_exhaustion: bool = False,
    ) -> LLMCompletion:
        """
        Run primary then optional fallback on transient provider failures only.

        When ``degrade_on_exhaustion`` is True, logs ``LLM_EXECUTION_FAILURE`` and
        returns a safe user-facing message instead of raising.
        """
        primary = self.resolve_primary_model(model)
        fallback_model, fallback_key, fallback_base = self._resolve_fallback_endpoint()

        try:
            result = await self._client.chat_completion(
                messages=messages,
                model=primary,
                temperature=temperature,
                tools=tools,
            )
            result = await self._maybe_force_tool_call(
                result,
                messages=messages,
                model=primary,
                temperature=temperature,
                tools=tools,
            )
            result = await self._resolve_tool_calls(
                result,
                messages=messages,
                model=primary,
                temperature=temperature,
                tools=tools,
                bot_id=bot_id,
                client_id=client_id,
                db=db,
            )
            result.primary_model = primary
            result.fallback_model = fallback_model
            result.used_fallback = False
            return result
        except TransientLLMError as primary_exc:
            logger.warning(
                "[LLM Fallback] Primary model failed with {error}, switching to fallback model {fallback}",
                error=f"{type(primary_exc).__name__}: {primary_exc}",
                fallback=fallback_model,
            )
            if not fallback_model or fallback_model == primary:
                return await self._handle_exhaustion(
                    primary_exc,
                    primary_model=primary,
                    fallback_model=fallback_model,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    db=db,
                    degrade_on_exhaustion=degrade_on_exhaustion,
                )
            try:
                result = await self._client.chat_completion(
                    messages=messages,
                    model=fallback_model,
                    temperature=temperature,
                    tools=tools,
                    api_key=fallback_key,
                    base_url=fallback_base,
                )
                result = await self._maybe_force_tool_call(
                    result,
                    messages=messages,
                    model=fallback_model,
                    temperature=temperature,
                    tools=tools,
                    api_key=fallback_key,
                    base_url=fallback_base,
                )
                result = await self._resolve_tool_calls(
                    result,
                    messages=messages,
                    model=fallback_model,
                    temperature=temperature,
                    tools=tools,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )
                result.primary_model = primary
                result.fallback_model = fallback_model
                result.used_fallback = True
                logger.info(
                    "[LLM Fallback] Fallback model succeeded | primary={primary} fallback={fallback}",
                    primary=primary,
                    fallback=fallback_model,
                )
                return result
            except Exception as fallback_exc:
                logger.error(
                    "[LLM Fallback] Fallback model failed | primary={primary} fallback={fallback} error={error}",
                    primary=primary,
                    fallback=fallback_model,
                    error=str(fallback_exc),
                )
                return await self._handle_exhaustion(
                    fallback_exc,
                    primary_model=primary,
                    fallback_model=fallback_model,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    db=db,
                    degrade_on_exhaustion=degrade_on_exhaustion,
                )

    async def _resolve_tool_calls(
        self,
        result: LLMCompletion,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        tools: list[dict[str, Any]] | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        db: AsyncSession | None,
    ) -> LLMCompletion:
        """Run one tool round-trip when the model returns function calls."""
        if not result.tool_calls or db is None or bot_id is None:
            return result

        from app.models.core_models import Bot, Client
        from app.services.llm.tool_executor import execute_tool_call

        bot = await db.get(Bot, bot_id)
        if bot is None:
            return result
        client: Client | None = None
        if client_id is not None:
            client = await db.get(Client, client_id)

        channel = "web"
        channel_user_id: str | None = None
        if client is not None:
            channel_user_id = client.external_id
            source = str(getattr(client, "source", "") or "").lower()
            if "telegram" in source:
                channel = "telegram"
            elif "whatsapp" in source or "wazzup" in source:
                channel = "whatsapp"
            elif "web" in source or "widget" in source:
                channel = "web"

        tools_executed: list[str] = []
        booking_ok = False
        collected_media: list[dict[str, Any]] = []
        fixed_reply_text = ""
        booking_tool_names = {
            "create_calendar_event",
            "save_lead_to_crm",
            "check_calendar_availability",
        }
        suppress_media = self._user_turn_suppresses_media_resend(messages)

        normalized_calls: list[dict[str, Any]] = []
        for tc in result.tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
            normalized_calls.append(
                {
                    "id": tc.get("id"),
                    "name": str((fn or {}).get("name") if fn else tc.get("name") or ""),
                    "arguments": str(
                        (fn or {}).get("arguments") if fn else tc.get("arguments") or "{}"
                    ),
                }
            )

        import json as _json

        from app.services.llm.tool_reply_sanitize import (
            is_tool_debug_text,
            sanitize_outbound_text,
        )

        # OpenAI-compatible APIs expect content=null on tool-only assistant turns.
        assistant_content = (result.text or "").strip() or None
        if assistant_content and is_tool_debug_text(assistant_content):
            assistant_content = None

        follow_up = list(messages)
        follow_up.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name"),
                            "arguments": tc.get("arguments"),
                        },
                    }
                    for tc in normalized_calls
                ],
            }
        )

        for tc in normalized_calls:
            tool_name = str(tc.get("name") or "")
            tool_result = await execute_tool_call(
                db,
                bot=bot,
                client=client,
                tool_name=tool_name,
                arguments_json=str(tc.get("arguments") or "{}"),
                channel=channel,
                channel_user_id=channel_user_id,
            )

            if tool_name:
                tools_executed.append(tool_name)
            if tool_name in booking_tool_names and self._tool_result_ok(tool_result):
                booking_ok = True
            if isinstance(tool_result, dict):
                media_items = tool_result.get("media_attachments")
                if isinstance(media_items, list) and not suppress_media:
                    for item in media_items:
                        if isinstance(item, dict) and item.get("url"):
                            collected_media.append(item)
                elif isinstance(media_items, list) and suppress_media and media_items:
                    logger.info(
                        "LLMOrchestrator.suppress_media_resend | bot_id={bot_id} tool={tool}",
                        bot_id=bot_id,
                        tool=tool_name,
                    )
                fixed_reply = str(tool_result.get("fixed_reply") or "").strip()
                if fixed_reply:
                    fixed_reply_text = fixed_reply

            follow_up.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": _json.dumps(tool_result, ensure_ascii=False),
                }
            )

        if fixed_reply_text:
            return LLMCompletion(
                text=fixed_reply_text,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                tools_executed=tools_executed,
                booking_tools_succeeded=booking_ok,
                media_attachments=collected_media or None,
            )

        # Second completion — model reads tool output and replies to the user.
        # Do not pass tools again: force a natural-language answer for the client.
        try:
            final = await self._client.chat_completion(
                messages=follow_up,
                model=model,
                temperature=temperature,
                tools=None,
                max_tokens=2048,
            )
        except Exception as primary_exc:
            # Tool follow-ups used to hit OpenRouter without max_tokens (65536 → 402).
            # Recover via Groq so the user still gets a reply after a successful tool run.
            fb_model, fb_key, fb_base = self._resolve_fallback_endpoint()
            if not fb_key or not fb_model or fb_model == model:
                raise
            logger.warning(
                "LLMOrchestrator.tool_followup_fallback | primary={primary} "
                "fallback={fallback} error={error}",
                primary=model,
                fallback=fb_model,
                error=f"{type(primary_exc).__name__}: {primary_exc}",
            )
            final = await self._client.chat_completion(
                messages=follow_up,
                model=fb_model,
                temperature=temperature,
                tools=None,
                api_key=fb_key,
                base_url=fb_base,
                max_tokens=2048,
            )
        final.tool_calls = None
        final.tools_executed = tools_executed
        final.booking_tools_succeeded = booking_ok
        final.media_attachments = collected_media or None

        final.text = sanitize_outbound_text(
            final.text,
            tools_executed=tools_executed,
            booking_ok=booking_ok,
        )
        if is_tool_debug_text(final.text) or not (final.text or "").strip():
            # Last resort: one more completion without tools asking for a plain reply.
            nudge = list(follow_up)
            nudge.append(
                {
                    "role": "user",
                    "content": (
                        "Сформируй короткий естественный ответ клиенту на русском "
                        "по результатам выполненных инструментов. Не вызывай tools."
                    ),
                }
            )
            try:
                retry = await self._client.chat_completion(
                    messages=nudge,
                    model=model,
                    temperature=temperature,
                    tools=None,
                    max_tokens=1024,
                )
                final.text = sanitize_outbound_text(
                    retry.text,
                    tools_executed=tools_executed,
                    booking_ok=booking_ok,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LLMOrchestrator.tool_reply_retry_failed | bot_id={bot_id} error={error}",
                    bot_id=bot_id,
                    error=str(exc),
                )
                try:
                    fb_model, fb_key, fb_base = self._resolve_fallback_endpoint()
                    if fb_key and fb_model:
                        retry = await self._client.chat_completion(
                            messages=nudge,
                            model=fb_model,
                            temperature=temperature,
                            tools=None,
                            api_key=fb_key,
                            base_url=fb_base,
                            max_tokens=1024,
                        )
                        final.text = sanitize_outbound_text(
                            retry.text,
                            tools_executed=tools_executed,
                            booking_ok=booking_ok,
                        )
                    else:
                        final.text = sanitize_outbound_text(
                            None,
                            tools_executed=tools_executed,
                            booking_ok=booking_ok,
                        )
                except Exception:
                    final.text = sanitize_outbound_text(
                        None,
                        tools_executed=tools_executed,
                        booking_ok=booking_ok,
                    )

        if final.text:
            logger.info(
                "LLMOrchestrator.tool_react_ok | bot_id={bot_id} tools={tools} reply_len={n}",
                bot_id=bot_id,
                tools=tools_executed,
                n=len(final.text),
            )

        # Photo tools often leave a «подождите, выполню расчёт» narration with no sum.
        # Height/calc corrections that suppressed media also need an immediate quote.
        ensured = await self._ensure_calc_delivered(
            final,
            messages=follow_up,
            model=model,
            temperature=temperature,
        )
        if (
            suppress_media
            and not self._text_has_calc_result(ensured.text or "")
            and self._user_turn_suppresses_media_resend(messages)
        ):
            ensured = await self._force_immediate_calc_text(
                ensured,
                messages=follow_up,
                model=model,
                temperature=temperature,
            )
        ensured.tools_executed = tools_executed
        ensured.booking_tools_succeeded = booking_ok
        if ensured.media_attachments is None and collected_media:
            ensured.media_attachments = collected_media
        return ensured

    @staticmethod
    def _tool_result_ok(tool_result: dict[str, Any] | Any) -> bool:
        if not isinstance(tool_result, dict):
            return False
        status = str(tool_result.get("status") or "").lower()
        if status in {"ok", "success", "created", "free", "busy"}:
            return True
        if tool_result.get("lead_id") or tool_result.get("event_id"):
            return True
        if tool_result.get("available") is not None:
            return True
        return False

    @staticmethod
    def _latest_user_text(messages: list[dict[str, Any]]) -> str:
        for item in reversed(messages):
            if not isinstance(item, dict):
                continue
            if item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text") or ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return " ".join(parts).strip()
        return ""

    @classmethod
    def _user_turn_suppresses_media_resend(cls, messages: list[dict[str, Any]]) -> bool:
        """
        Height/length/color corrections and «отправьте расчёт» must not re-fire
        the catalog photo tool that was already used earlier in the dialog.
        """
        user_text = cls._latest_user_text(messages)
        if not user_text:
            return False
        if _PHOTO_INTENT_PATTERN.search(user_text) and not _CALC_INTENT_PATTERN.search(
            user_text
        ):
            return False
        correction = re.compile(
            r"(?i)("
            r"высот|длин[аыуе]|"
            r"расч[её]т|стоимост|отправ(?:ьте|и)\s+расч|"
            r"\d+[.,]\d+\s*м?(?:\b|$)|"
            r"\b\d{2,}\s*м(?:етр)?\b"
            r")"
        )
        return bool(correction.search(user_text))

    @staticmethod
    def _tool_fn_meta(tool: dict[str, Any]) -> tuple[str, str]:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if not isinstance(fn, dict):
            return "", ""
        return str(fn.get("name") or ""), str(fn.get("description") or "")

    @classmethod
    def _classify_wait_intent(cls, text: str) -> WaitIntent:
        raw = (text or "").strip()
        if not raw or not _WAIT_PATTERN.search(raw):
            return "none"
        wants_calc = bool(_CALC_INTENT_PATTERN.search(raw))
        wants_photo = bool(_PHOTO_INTENT_PATTERN.search(raw))
        if wants_calc and wants_photo:
            return "both"
        if wants_calc:
            return "calc"
        if wants_photo:
            return "photo"
        return "wait"

    @classmethod
    def _text_has_calc_result(cls, text: str) -> bool:
        return bool(_CALC_RESULT_PATTERN.search(text or ""))

    @classmethod
    def _is_calc_tool(cls, tool: dict[str, Any]) -> bool:
        name, description = cls._tool_fn_meta(tool)
        blob = f"{name} {description}"
        return bool(_CALC_TOOL_PATTERN.search(blob))

    @classmethod
    def _is_media_tool(cls, tool: dict[str, Any]) -> bool:
        name, description = cls._tool_fn_meta(tool)
        blob = f"{name} {description}"
        if _MEDIA_TOOL_PATTERN.search(blob):
            return True
        # Workspace photo tools are annotated to "Call … for photos/files/samples".
        return "same turn whenever the user asks for photos" in description.lower()

    async def _force_immediate_calc_text(
        self,
        result: LLMCompletion,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> LLMCompletion:
        """Replace a wait-for-calc narration with an actual quote in the same turn."""
        text = (result.text or "").strip()
        nudge = list(messages)
        if text:
            nudge.append({"role": "assistant", "content": text})
        nudge.append({"role": "user", "content": _CALC_NUDGE})
        try:
            forced = await self._client.chat_completion(
                messages=nudge,
                model=model,
                temperature=min(temperature, 0.3),
                tools=None,
                api_key=api_key,
                base_url=base_url,
                max_tokens=2048,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLMOrchestrator.force_calc_text_failed | model={model} error={error}",
                model=model,
                error=str(exc),
            )
            return result
        out_text = (forced.text or "").strip()
        if not out_text:
            return result
        logger.info(
            "LLMOrchestrator.force_calc_text_ok | model={model} reply_len={n}",
            model=model,
            n=len(out_text),
        )
        forced.tool_calls = None
        forced.media_attachments = result.media_attachments
        forced.tools_executed = result.tools_executed
        forced.booking_tools_succeeded = result.booking_tools_succeeded
        return forced

    async def _ensure_calc_delivered(
        self,
        result: LLMCompletion,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> LLMCompletion:
        text = (result.text or "").strip()
        intent = self._classify_wait_intent(text)
        if intent not in {"calc", "both", "wait"}:
            return result
        if intent == "wait" and not _CALC_INTENT_PATTERN.search(text):
            # Generic «подождите» after photo send without calc wording — leave as is.
            return result
        if self._text_has_calc_result(text):
            return result
        return await self._force_immediate_calc_text(
            result,
            messages=messages,
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
        )

    async def _maybe_force_tool_call(
        self,
        result: LLMCompletion,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        tools: list[dict[str, Any]] | None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> LLMCompletion:
        """
        If the model narrates «подождите / отправлю фото / выполню расчет»
        without tool_calls, force the matching delivery in this turn.

        Calc promises must NOT re-fire photo tools (that duplicated samples and
        never produced the quote). When no calc tool exists, force a text quote.
        """
        if result.tool_calls:
            return result
        text = (result.text or "").strip()
        if not text:
            return result
        intent = self._classify_wait_intent(text)
        if intent == "none":
            return result

        # Calculation promised → deliver numbers now (prefer calc tools, else text).
        if intent in {"calc", "both"}:
            calc_tools = [t for t in (tools or []) if self._is_calc_tool(t)]
            if not calc_tools:
                return await self._force_immediate_calc_text(
                    result,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    api_key=api_key,
                    base_url=base_url,
                )
            tools = calc_tools
        elif intent == "photo":
            media_tools = [t for t in (tools or []) if self._is_media_tool(t)]
            if media_tools:
                tools = media_tools
            elif not tools:
                return result
        else:
            # Generic wait: only force tools if we have media tools AND photo wording
            # was absent — otherwise avoid re-sending files.
            if not tools:
                return await self._force_immediate_calc_text(
                    result,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    api_key=api_key,
                    base_url=base_url,
                )
            media_tools = [t for t in tools if self._is_media_tool(t)]
            calc_tools = [t for t in tools if self._is_calc_tool(t)]
            if calc_tools:
                tools = calc_tools
            elif media_tools and len(media_tools) == len(tools):
                # Only photo tools exist for a vague wait → ask for the quote in text
                # so we do not spam the last catalog image again.
                return await self._force_immediate_calc_text(
                    result,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    api_key=api_key,
                    base_url=base_url,
                )

        if not tools:
            return result

        nudge = list(messages)
        nudge.append({"role": "assistant", "content": text})
        nudge.append(
            {
                "role": "user",
                "content": (
                    "Не обещай отправку позже. Сейчас же вызови нужную function "
                    "через tool call в этом же ходе. Для расчёта сохраняй дробную "
                    "высоту точно (3,5 → 3.5)."
                    if intent in {"calc", "both", "wait"}
                    else "Не обещай отправку позже. Сейчас же вызови function "
                    "для фото/файла через tool call в этом же ходе."
                ),
            }
        )
        try:
            forced = await self._client.chat_completion(
                messages=nudge,
                model=model,
                temperature=temperature,
                tools=tools,
                tool_choice="required",
                api_key=api_key,
                base_url=base_url,
                max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLMOrchestrator.force_tool_failed | model={model} error={error}",
                model=model,
                error=str(exc),
            )
            if intent in {"calc", "both", "wait"}:
                return await self._force_immediate_calc_text(
                    result,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    api_key=api_key,
                    base_url=base_url,
                )
            return result
        if forced.tool_calls:
            logger.info(
                "LLMOrchestrator.force_tool_ok | model={model} intent={intent} tools={n}",
                model=model,
                intent=intent,
                n=len(forced.tool_calls),
            )
            return forced
        if intent in {"calc", "both", "wait"}:
            return await self._force_immediate_calc_text(
                result,
                messages=messages,
                model=model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
            )
        return result

    async def _handle_exhaustion(
        self,
        exc: BaseException,
        *,
        primary_model: str,
        fallback_model: str,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        node_id: str | None,
        db: AsyncSession | None,
        degrade_on_exhaustion: bool,
    ) -> LLMCompletion:
        message = format_execution_failure_message(
            provider_error=str(exc),
            primary_model=primary_model,
            fallback_model=fallback_model,
        )
        # Only persist diagnostics when we are done retrying (graceful degrade path).
        # Celery callers keep ``degrade_on_exhaustion=False`` so they can retry first.
        if degrade_on_exhaustion:
            await self.record_execution_failure(
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                message=message,
                db=db,
            )
            return LLMCompletion(
                text=self.SAFE_FALLBACK_MESSAGE,
                model=fallback_model or primary_model,
                primary_model=primary_model,
                fallback_model=fallback_model,
                used_fallback=True,
            )
        if isinstance(exc, TransientLLMError):
            raise exc
        raise TransientLLMError(str(exc), model=primary_model, cause=exc) from exc

    async def record_execution_failure(
        self,
        *,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        node_id: str | None,
        message: str,
        db: AsyncSession | None = None,
    ) -> None:
        if bot_id is None:
            logger.error("LLMOrchestrator.execution_failure | {message}", message=message)
            return

        error_type = DiagnosticErrorType.LLM_EXECUTION_FAILURE
        try:
            if db is not None:
                await diagnostic_log_service.log(
                    db,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=error_type,
                    error_message=message,
                    node_id=node_id,
                )
            else:
                diagnostic_log_service.schedule_log(
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=error_type,
                    error_message=message,
                    node_id=node_id,
                )
        except Exception as log_exc:
            logger.exception(
                "LLMOrchestrator.diagnostic_log_failed | error={error}",
                error=str(log_exc),
            )


llm_orchestrator = LLMOrchestrator()
