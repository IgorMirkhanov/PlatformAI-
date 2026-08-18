"""API request node — outbound HTTP with SSRF protection."""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from app.core.url_safety import assert_safe_public_https_url
from app.services.flow.engine import FlowEngineError
from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
)


class ApiRequestNodeHandler(BaseNodeHandler):
    node_types = ("api_request", "http_request", "webhook_request")

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._http_client = http_client
        self.timeout_seconds = float(timeout_seconds)

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        data = ctx.data
        raw_url = ctx.interpolate(str(data.get("url") or ""))
        if not raw_url:
            raise FlowEngineError("API request node requires a url.")

        try:
            safe_url = assert_safe_public_https_url(raw_url)
        except ValueError as exc:
            logger.warning(
                "Flow.API.ssrf_blocked | session={sid} url={url} error={error}",
                sid=ctx.session.session_id,
                url=raw_url[:200],
                error=str(exc),
            )
            raise FlowEngineError(f"SSRF guard blocked URL: {exc}") from exc

        method = str(data.get("method") or "GET").strip().upper()
        headers = data.get("headers") if isinstance(data.get("headers"), dict) else {}
        # Interpolate string header values.
        resolved_headers = {
            str(k): ctx.interpolate(str(v)) if isinstance(v, str) else v
            for k, v in headers.items()
        }
        body = data.get("body")
        if isinstance(body, str):
            body = ctx.interpolate(body)
        elif isinstance(body, dict):
            body = {
                k: ctx.interpolate(v) if isinstance(v, str) else v for k, v in body.items()
            }

        response_var = str(data.get("response_variable") or "api_response")
        status_var = str(data.get("status_variable") or "api_status_code")

        client = self._http_client
        owns_client = client is None
        try:
            if client is None:
                client = httpx.AsyncClient(timeout=self.timeout_seconds)
            response = await client.request(
                method,
                safe_url,
                headers=resolved_headers,
                json=body if isinstance(body, (dict, list)) else None,
                content=body.encode("utf-8") if isinstance(body, str) else None,
            )
        except httpx.HTTPError as exc:
            raise FlowEngineError(f"API request failed: {exc}") from exc
        finally:
            if owns_client and client is not None:
                await client.aclose()

        try:
            parsed: Any = response.json()
        except Exception:
            parsed = response.text

        ctx.variables[response_var] = parsed
        ctx.variables[status_var] = int(response.status_code)
        ctx.variables["api_response"] = parsed

        return NodeHandlerResult(
            event="api_request",
            output={
                "url": safe_url,
                "method": method,
                "status_code": int(response.status_code),
                "response_variable": response_var,
                "body_preview": _preview(parsed),
            },
        )


def _preview(value: Any, limit: int = 200) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    return text[:limit]
