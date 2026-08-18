"""CRM automation condition evaluator — reuses FlowExecutor DSL from flow_parser."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal
from app.services.flow_parser import FlowExecutor


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        try:
            return str(value.value)
        except Exception:
            pass
    return str(value)


class AutomationEvaluatorService:
    """
    Evaluate ``crm_automation_rules.conditions`` using the same condition DSL
    as FlowExecutor (``condition_type`` / ``expression`` / ``customer_tag``).

    Context variables (available to the matcher via ``FlowExecutor.variables``):
    ``deal.amount``, ``deal.status``, ``deal.currency``, ``deal.stage_id``,
    ``deal.pipeline_id``, ``contact.source``, ``contact.tags`` / ``tags``.
    """

    def build_context(
        self,
        deal: CrmDeal,
        *,
        contact: CrmContact | None = None,
        tags: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tag_names = [str(t) for t in (tags or []) if str(t).strip()]
        status = getattr(deal.status, "value", deal.status)
        amount = deal.amount if deal.amount is not None else Decimal("0")

        flat: dict[str, Any] = {
            "deal.amount": amount,
            "deal.status": status,
            "deal.currency": deal.currency,
            "deal.stage_id": str(deal.stage_id) if deal.stage_id else "",
            "deal.pipeline_id": str(deal.pipeline_id) if deal.pipeline_id else "",
            "deal.title": deal.title or "",
            "deal.source": getattr(deal, "source", None) or "",
            "deal.id": str(deal.id) if deal.id else "",
            "contact.source": (contact.source if contact is not None else "") or "",
            "contact.tags": tag_names,
            "tags": tag_names,
            "amount": amount,
            "status": status,
            "currency": deal.currency,
            "stage_id": str(deal.stage_id) if deal.stage_id else "",
            "pipeline_id": str(deal.pipeline_id) if deal.pipeline_id else "",
        }
        if contact is not None:
            flat["contact.id"] = str(contact.id)
            flat["contact.email"] = contact.email or ""
            flat["contact.phone"] = contact.phone or ""
            flat["contact.first_name"] = contact.first_name or ""
            flat["contact.last_name"] = contact.last_name or ""

        custom = getattr(deal, "custom_fields", None) or {}
        if isinstance(custom, dict):
            for key, value in custom.items():
                flat[f"deal.custom.{key}"] = value
                flat[f"custom.{key}"] = value

        if extra:
            for key, value in extra.items():
                flat[str(key)] = value

        # Haystack for expression / keyword matching (FlowExecutor._condition_matches).
        flat["message"] = "\n".join(
            f"{key}={_stringify(value)}" for key, value in flat.items() if key != "message"
        )
        return flat

    def evaluate(self, conditions: dict[str, Any] | None, context: dict[str, Any]) -> bool:
        """
        Return True when conditions pass (or are empty).

        Supported shapes (same family as flow_parser condition node ``data``):
        - ``{}`` / ``None`` / empty rules → True
        - ``{"condition_type": "...", "expression": "..."}`` → FlowExecutor matcher
        - ``{"op": "and"|"or", "rules": [ <condition>, ... ]}`` → combine matchers
        """
        if not conditions:
            return True
        if not isinstance(conditions, dict):
            return False

        if "rules" in conditions:
            rules = conditions.get("rules") or []
            if not isinstance(rules, list) or not rules:
                return True
            op = str(conditions.get("op") or "and").strip().lower()
            results = [self.evaluate(rule if isinstance(rule, dict) else {}, context) for rule in rules]
            if op == "or":
                return any(results)
            return all(results)

        # Bare expression string convenience
        if set(conditions.keys()) <= {"expression", "condition_type", "tag"} or (
            "expression" in conditions or "condition_type" in conditions or "tag" in conditions
        ):
            return self._match_flow_condition(conditions, context)

        # Unknown non-empty dict without recognizable keys → fail closed only if
        # it looks intentional; treat pure metadata as pass.
        return True

    def _match_flow_condition(self, data: dict[str, Any], context: dict[str, Any]) -> bool:
        expression = str(data.get("expression") or "").strip()
        condition_type = str(data.get("condition_type") or "expression").strip()
        if condition_type == "expression" and not expression:
            return True
        if expression.casefold() in {"true", "1", "yes"}:
            return True
        if expression.casefold() in {"false", "0", "no"}:
            return False

        executor = FlowExecutor({"nodes": [], "edges": []})
        executor.variables = dict(context)
        executor.variables.setdefault("tags", context.get("tags") or [])
        message = str(context.get("message") or "")
        return bool(executor._condition_matches(data, message))


automation_evaluator_service = AutomationEvaluatorService()
