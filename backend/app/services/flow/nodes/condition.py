"""Condition node — True/False branching on session variables."""

from __future__ import annotations

from typing import Any

from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
    resolve_branch_edge,
)


def _coerce_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(
    *,
    left: Any,
    operator: str,
    right: Any,
) -> bool:
    op = (operator or "equals").strip().lower().replace(" ", "_")
    if op in {"equals", "eq", "==", "is"}:
        return str(left) == str(right)
    if op in {"not_equals", "neq", "!=", "is_not"}:
        return str(left) != str(right)
    if op in {"contains", "includes"}:
        return str(right) in str(left)
    if op in {"not_contains", "excludes"}:
        return str(right) not in str(left)
    if op in {"greater_than", "gt", ">"}:
        ln, rn = _coerce_number(left), _coerce_number(right)
        return ln is not None and rn is not None and ln > rn
    if op in {"less_than", "lt", "<"}:
        ln, rn = _coerce_number(left), _coerce_number(right)
        return ln is not None and rn is not None and ln < rn
    if op in {"greater_or_equal", "gte", ">="}:
        ln, rn = _coerce_number(left), _coerce_number(right)
        return ln is not None and rn is not None and ln >= rn
    if op in {"less_or_equal", "lte", "<="}:
        ln, rn = _coerce_number(left), _coerce_number(right)
        return ln is not None and rn is not None and ln <= rn
    if op in {"exists", "truthy"}:
        return bool(left)
    if op in {"empty", "falsy"}:
        return not bool(left)
    return str(left) == str(right)


class ConditionNodeHandler(BaseNodeHandler):
    node_types = ("condition", "if", "branch")

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        data = ctx.data
        variable = str(data.get("variable") or data.get("field") or "").strip()
        operator = str(data.get("operator") or "equals")
        expected = data.get("value", data.get("equals"))

        if variable.startswith("{{") and variable.endswith("}}"):
            left = ctx.interpolate(variable)
        else:
            left = ctx.variables.get(variable)

        # Allow templated comparison value.
        if isinstance(expected, str) and "{{" in expected:
            expected = ctx.interpolate(expected)

        matched = evaluate_condition(left=left, operator=operator, right=expected)
        branch = "true" if matched else "false"
        ctx.variables["branch"] = branch
        ctx.variables["condition_result"] = matched

        next_id = resolve_branch_edge(ctx.outgoing_edges, branch)
        return NodeHandlerResult(
            event="condition",
            branch=branch,
            next_node_id=next_id,
            output={
                "variable": variable,
                "operator": operator,
                "left": left,
                "right": expected,
                "matched": matched,
            },
        )
