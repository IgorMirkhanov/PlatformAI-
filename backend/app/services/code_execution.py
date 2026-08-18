from __future__ import annotations

from typing import Any

from loguru import logger

SAFE_BUILTINS: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "len": len,
    "min": min,
    "max": max,
    "sum": sum,
    "range": range,
    "enumerate": enumerate,
    "sorted": sorted,
    "round": round,
    "abs": abs,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "print": lambda *_args, **_kwargs: None,
}


def execute_custom_code_snippet(
    snippet: str,
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute user-provided Python snippet in a restricted namespace.

    The snippet may assign to `result` or mutate `context`.
    """
    cleaned = (snippet or "").strip()
    if not cleaned:
        return {
            "success": True,
            "result": None,
            "message": "No custom code configured.",
            "error": None,
        }

    local_ns: dict[str, Any] = {}
    global_ns: dict[str, Any] = {
        "__builtins__": SAFE_BUILTINS,
        "context": dict(context),
        "result": None,
    }

    try:
        exec(cleaned, global_ns, local_ns)  # noqa: S102 — intentional sandbox hook
        output = local_ns.get("result", global_ns.get("result"))
        merged_context = global_ns.get("context", context)
        logger.info(
            "CustomCode.executed | success=true result_type={result_type}",
            result_type=type(output).__name__,
        )
        return {
            "success": True,
            "result": output,
            "context": merged_context if isinstance(merged_context, dict) else context,
            "message": "Custom code executed successfully.",
            "error": None,
        }
    except Exception as exc:
        logger.exception("CustomCode.execution_failed | error={error}", error=str(exc))
        return {
            "success": False,
            "result": None,
            "context": context,
            "message": f"Custom code execution failed: {exc}",
            "error": str(exc),
        }
