"""CRM automation executor — trigger matching, condition eval, action runner."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_safety import assert_safe_public_https_url
from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal
from app.repositories.crm.automation_rule_repository import automation_rule_repository
from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.deal_repository import deal_repository
from app.schemas.crm.activities_notes import CrmNoteCreate
from app.services.crm.automation_evaluator_service import automation_evaluator_service

WEBHOOK_TIMEOUT_SECONDS = 10.0
_MAX_ACTIONS_PER_RULE = 20


class AutomationExecutorService:
    """
    Load active rules for a trigger, evaluate conditions (flow_parser DSL),
    and run actions (``move_stage``, ``add_tag``, ``add_note``, ``send_webhook``).
    """

    def _rules_repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return automation_rule_repository(db, organization_id=organization_id)

    async def run_triggers(
        self,
        db: AsyncSession,
        trigger_type: AutomationTriggerType,
        deal: CrmDeal,
        context_extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Evaluate and execute all active rules for ``trigger_type`` in the deal's org.

        Returns a list of per-rule result dicts (for tests / diagnostics).
        Failures on individual rules/actions are logged and skipped — never raise
        into the calling deal mutation.
        """
        organization_id = deal.organization_id
        results: list[dict[str, Any]] = []
        try:
            rules = await self._rules_repo(db, organization_id).get_active_rules_by_trigger(
                trigger_type
            )
        except Exception as exc:
            logger.exception(
                "CRM.automation_rules_load_failed | org={org} trigger={trigger} error={error}",
                org=organization_id,
                trigger=trigger_type.value,
                error=str(exc),
            )
            return results

        if not rules:
            return results

        contact = await self._load_contact(db, organization_id, deal.contact_id)
        tag_names = await self._load_deal_tag_names(db, organization_id, deal.id)
        context = automation_evaluator_service.build_context(
            deal,
            contact=contact,
            tags=tag_names,
            extra=context_extra,
        )

        for rule in rules:
            rule_result: dict[str, Any] = {
                "rule_id": str(rule.id),
                "name": rule.name,
                "matched": False,
                "actions_run": [],
                "skipped_reason": None,
            }
            try:
                if not self._trigger_config_matches(rule, deal, context_extra):
                    rule_result["skipped_reason"] = "trigger_config"
                    results.append(rule_result)
                    continue
                if not automation_evaluator_service.evaluate(rule.conditions or {}, context):
                    rule_result["skipped_reason"] = "conditions"
                    results.append(rule_result)
                    continue

                rule_result["matched"] = True
                actions = list(rule.actions or [])[:_MAX_ACTIONS_PER_RULE]
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    action_type = str(action.get("type") or "").strip()
                    if not action_type:
                        continue
                    try:
                        await self._run_action(
                            db,
                            organization_id,
                            deal,
                            action,
                            contact=contact,
                        )
                        rule_result["actions_run"].append(action_type)
                        # Refresh deal after mutations that change stage / relations
                        refreshed = await deal_repository(
                            db, organization_id=organization_id
                        ).get_with_relations(deal.id)
                        if refreshed is not None:
                            deal = refreshed
                    except Exception as action_exc:
                        logger.warning(
                            "CRM.automation_action_failed | rule_id={rule_id} "
                            "action={action} deal_id={deal_id} error={error}",
                            rule_id=rule.id,
                            action=action_type,
                            deal_id=deal.id,
                            error=str(action_exc),
                        )
            except Exception as rule_exc:
                logger.exception(
                    "CRM.automation_rule_failed | rule_id={rule_id} error={error}",
                    rule_id=rule.id,
                    error=str(rule_exc),
                )
                rule_result["skipped_reason"] = "error"
            results.append(rule_result)

        logger.info(
            "CRM.automations_ran | org={org} trigger={trigger} deal_id={deal_id} "
            "rules={count} matched={matched}",
            org=organization_id,
            trigger=trigger_type.value,
            deal_id=deal.id,
            count=len(rules),
            matched=sum(1 for r in results if r.get("matched")),
        )
        return results

    @staticmethod
    def _trigger_config_matches(
        rule: CrmAutomationRule,
        deal: CrmDeal,
        context_extra: dict[str, Any] | None,
    ) -> bool:
        cfg = rule.trigger_config if isinstance(rule.trigger_config, dict) else {}
        if not cfg:
            return True

        trigger = rule.trigger_type
        if trigger == AutomationTriggerType.STAGE_ENTERED:
            wanted = cfg.get("stage_id")
            if wanted and str(wanted) != str(deal.stage_id):
                return False
            return True

        if trigger == AutomationTriggerType.DEAL_CREATED:
            wanted_pipeline = cfg.get("pipeline_id")
            if wanted_pipeline and str(wanted_pipeline) != str(deal.pipeline_id):
                return False
            wanted_stage = cfg.get("stage_id")
            if wanted_stage and str(wanted_stage) != str(deal.stage_id):
                return False
            return True

        if trigger == AutomationTriggerType.FIELD_CHANGED:
            field = str(cfg.get("field") or cfg.get("field_key") or "").strip()
            if not field:
                return True
            extra = context_extra or {}
            changed = extra.get("changed_fields") or extra.get("field") or ""
            if isinstance(changed, (list, tuple, set)):
                return field in {str(x) for x in changed}
            return str(changed) == field

        if trigger == AutomationTriggerType.TAG_ADDED:
            wanted = cfg.get("tag_id")
            if not wanted:
                return True
            extra = context_extra or {}
            return str(extra.get("tag_id") or "") == str(wanted)

        if trigger == AutomationTriggerType.NO_ACTIVITY_FOR:
            # Periodic Celery job supplies days_idle in context_extra.
            days_required = cfg.get("days") or cfg.get("days_idle")
            if days_required is None:
                return True
            extra = context_extra or {}
            try:
                return float(extra.get("days_idle") or 0) >= float(days_required)
            except (TypeError, ValueError):
                return False

        return True

    async def _load_contact(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID | None,
    ) -> CrmContact | None:
        if contact_id is None:
            return None
        try:
            return await contact_repository(db, organization_id=organization_id).get(contact_id)
        except Exception:
            return None

    async def _load_deal_tag_names(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
    ) -> list[str]:
        try:
            deal = await deal_repository(db, organization_id=organization_id).get_with_relations(
                deal_id
            )
            if deal is None:
                return []
            tags = getattr(deal, "tags", None) or []
            return [str(t.name) for t in tags if getattr(t, "name", None)]
        except Exception:
            return []

    async def _run_action(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal: CrmDeal,
        action: dict[str, Any],
        *,
        contact: CrmContact | None,
    ) -> None:
        action_type = str(action.get("type") or "").strip()
        if action_type == "move_stage":
            await self._action_move_stage(db, organization_id, deal, action)
        elif action_type == "add_tag":
            await self._action_add_tag(db, organization_id, deal, action)
        elif action_type == "add_note":
            await self._action_add_note(db, organization_id, deal, action, contact=contact)
        elif action_type == "send_webhook":
            await self._action_send_webhook(deal, action, contact=contact)
        else:
            logger.info(
                "CRM.automation_action_skipped_unknown | type={type} deal_id={deal_id}",
                type=action_type,
                deal_id=deal.id,
            )

    async def _action_move_stage(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal: CrmDeal,
        action: dict[str, Any],
    ) -> None:
        from app.services.crm.deal_service import deal_service

        stage_id_raw = action.get("stage_id")
        if not stage_id_raw:
            raise ValueError("move_stage requires stage_id")
        stage_id = uuid.UUID(str(stage_id_raw))
        await deal_service.move_stage(
            db,
            organization_id,
            deal.id,
            stage_id,
            skip_automations=True,
        )

    async def _action_add_tag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal: CrmDeal,
        action: dict[str, Any],
    ) -> None:
        from app.services.crm.tag_service import tag_service

        tag_id_raw = action.get("tag_id")
        if not tag_id_raw:
            raise ValueError("add_tag requires tag_id")
        tag_id = uuid.UUID(str(tag_id_raw))
        await tag_service.attach_tag_to_deal(db, organization_id, deal.id, tag_id)

    async def _action_add_note(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal: CrmDeal,
        action: dict[str, Any],
        *,
        contact: CrmContact | None,
    ) -> None:
        from app.services.crm.note_service import note_service

        text = str(action.get("text") or action.get("body") or "").strip()
        if not text:
            raise ValueError("add_note requires text")
        await note_service.create_note(
            db,
            organization_id,
            CrmNoteCreate(
                text=text,
                deal_id=deal.id,
                contact_id=deal.contact_id or (contact.id if contact else None),
            ),
        )

    async def _action_send_webhook(
        self,
        deal: CrmDeal,
        action: dict[str, Any],
        *,
        contact: CrmContact | None,
    ) -> None:
        url = str(action.get("url") or "").strip()
        safe_url = assert_safe_public_https_url(url)
        method = str(action.get("method") or "POST").upper()
        if method not in {"GET", "POST", "PUT"}:
            method = "POST"
        payload = {
            "event": "crm_automation",
            "deal_id": str(deal.id),
            "organization_id": str(deal.organization_id),
            "pipeline_id": str(deal.pipeline_id),
            "stage_id": str(deal.stage_id),
            "title": deal.title,
            "amount": str(deal.amount) if deal.amount is not None else None,
            "currency": deal.currency,
            "status": getattr(deal.status, "value", deal.status),
            "contact_id": str(deal.contact_id) if deal.contact_id else None,
            "contact_email": contact.email if contact else None,
        }
        body_extra = action.get("body")
        if isinstance(body_extra, dict):
            payload.update(body_extra)

        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False) as client:
            if method == "GET":
                response = await client.get(safe_url)
            elif method == "PUT":
                response = await client.put(safe_url, json=payload)
            else:
                response = await client.post(safe_url, json=payload)
        logger.info(
            "CRM.automation_webhook_sent | deal_id={deal_id} status={status} url_host={host}",
            deal_id=deal.id,
            status=response.status_code,
            host=httpx.URL(safe_url).host,
        )


automation_executor_service = AutomationExecutorService()


def enqueue_automation_run(
    *,
    organization_id: uuid.UUID,
    deal_id: uuid.UUID,
    trigger_type: AutomationTriggerType,
    context_extra: dict[str, Any] | None = None,
) -> bool:
    """
    Fire-and-forget on ``crm_actions`` Celery queue.

    Returns True when the task was accepted by the broker.
    """
    try:
        from app.tasks.crm_tasks import run_automation_task

        run_automation_task.apply_async(
            args=[
                str(organization_id),
                str(deal_id),
                trigger_type.value,
                context_extra or {},
            ]
        )
        return True
    except Exception as exc:
        logger.warning(
            "CRM.automation_enqueue_failed | deal_id={deal_id} trigger={trigger} error={error}",
            deal_id=deal_id,
            trigger=trigger_type.value,
            error=str(exc),
        )
        return False
