"""CRM action node — deal/contact mutations from session context."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Awaitable, Callable

from loguru import logger

from app.services.flow.engine import FlowEngineError
from app.services.flow.nodes.base import (
    BaseNodeHandler,
    NodeExecutionContext,
    NodeHandlerResult,
)

CrmActionFn = Callable[..., Awaitable[Any]]


class CrmActionNodeHandler(BaseNodeHandler):
    node_types = ("crm_action", "crm")

    def __init__(
        self,
        *,
        create_contact_fn: CrmActionFn | None = None,
        create_deal_fn: CrmActionFn | None = None,
    ) -> None:
        self._create_contact_fn = create_contact_fn
        self._create_deal_fn = create_deal_fn

    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        data = ctx.data
        action = str(data.get("action") or data.get("crm_action") or "").strip().lower()
        if not action:
            raise FlowEngineError("CRM action node requires data.action.")

        org_id = ctx.organization_id
        if org_id is None:
            raw = ctx.variables.get("organization_id")
            if raw:
                org_id = uuid.UUID(str(raw))
        if ctx.db is None or org_id is None:
            raise FlowEngineError("CRM action node requires db + organization_id.")

        if action in {"create_contact", "contact.create", "add_contact"}:
            result = await self._create_contact(ctx, org_id, data)
            ctx.variables["crm_contact_id"] = str(result.get("id") or "")
            ctx.variables["crm_last_action"] = "create_contact"
            return NodeHandlerResult(event="crm_action", output={"action": action, **result})

        if action in {"create_deal", "deal.create", "add_deal"}:
            result = await self._create_deal(ctx, org_id, data)
            ctx.variables["crm_deal_id"] = str(result.get("id") or "")
            ctx.variables["crm_last_action"] = "create_deal"
            return NodeHandlerResult(event="crm_action", output={"action": action, **result})

        raise FlowEngineError(f"Unsupported CRM action '{action}'.")

    async def _create_contact(
        self,
        ctx: NodeExecutionContext,
        organization_id: uuid.UUID,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        first_name = ctx.interpolate(
            str(data.get("first_name") or ctx.variables.get("first_name") or "Lead")
        )
        last_name = ctx.interpolate(
            str(data.get("last_name") or ctx.variables.get("last_name") or "")
        )
        phone = data.get("phone") or ctx.variables.get("phone") or ctx.variables.get("sender_id")
        email = data.get("email") or ctx.variables.get("email")

        if self._create_contact_fn is not None:
            created = await self._create_contact_fn(
                ctx.db,
                organization_id,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                email=email,
            )
            return _as_dict(created)

        from app.schemas.crm.accounts_contacts import CrmContactCreate
        from app.services.crm.contact_service import contact_service

        payload = CrmContactCreate(
            first_name=first_name,
            last_name=last_name or "",
            phone=str(phone) if phone else None,
            email=str(email) if email else None,
            source=str(data.get("source") or "flow"),
        )
        created = await contact_service.create_contact(ctx.db, organization_id, payload)
        logger.info(
            "Flow.CRM.create_contact | org={org} contact={id}",
            org=organization_id,
            id=created.id,
        )
        return created.model_dump(mode="json")

    async def _create_deal(
        self,
        ctx: NodeExecutionContext,
        organization_id: uuid.UUID,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        title = ctx.interpolate(
            str(data.get("title") or ctx.variables.get("deal_title") or "Flow deal")
        )
        pipeline_id = data.get("pipeline_id") or ctx.variables.get("pipeline_id")
        stage_id = data.get("stage_id") or ctx.variables.get("stage_id")
        if not pipeline_id or not stage_id:
            raise FlowEngineError(
                "CRM create_deal requires pipeline_id and stage_id in node data or session."
            )

        amount = data.get("amount", ctx.variables.get("deal_amount", 0))
        try:
            amount_dec = Decimal(str(amount))
        except Exception:
            amount_dec = Decimal("0.00")

        if self._create_deal_fn is not None:
            created = await self._create_deal_fn(
                ctx.db,
                organization_id,
                title=title,
                pipeline_id=uuid.UUID(str(pipeline_id)),
                stage_id=uuid.UUID(str(stage_id)),
                amount=amount_dec,
            )
            return _as_dict(created)

        from app.schemas.crm.deals import CrmDealCreate
        from app.services.crm.deal_service import deal_service

        contact_id = data.get("contact_id") or ctx.variables.get("crm_contact_id")
        payload = CrmDealCreate(
            title=title,
            pipeline_id=uuid.UUID(str(pipeline_id)),
            stage_id=uuid.UUID(str(stage_id)),
            amount=amount_dec,
            contact_id=uuid.UUID(str(contact_id)) if contact_id else None,
            source=str(data.get("source") or "flow"),
        )
        created = await deal_service.create_deal(ctx.db, organization_id, payload)
        logger.info(
            "Flow.CRM.create_deal | org={org} deal={id}",
            org=organization_id,
            id=created.id,
        )
        return created.model_dump(mode="json")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "id"):
        return {"id": str(value.id)}
    return {"result": str(value)}
