"""CRM Bridge — Flow Builder ``target=internal`` actions against native CRM."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.core_models import Client
from app.models.crm.deal import DealStatus
from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.deal_repository import deal_repository
from app.schemas.crm.activities_notes import CrmNoteCreate
from app.services.crm.deal_service import DealServiceError, deal_service
from app.services.crm.note_service import NoteServiceError, note_service
from app.services.crm.tag_service import TagServiceError, tag_service


class CrmBridgeServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


SUPPORTED_INTERNAL_ACTIONS = frozenset({"move_stage", "add_note", "add_tag"})


class CrmBridgeService:
    """Routes Flow ``crm_action`` nodes with ``target=internal`` into native CRM services."""

    async def execute_internal_action(
        self,
        db: AsyncSession,
        client_id: uuid.UUID,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        action_name = (action or "").strip().lower()
        if action_name not in SUPPORTED_INTERNAL_ACTIONS:
            return {
                "success": False,
                "error": f"Unsupported internal CRM action: {action_name or '(empty)'}",
            }

        organization_id, contact = await self._resolve_contact(db, client_id)
        if organization_id is None or contact is None:
            logger.info(
                "CrmBridge.no_contact | client_id={client_id} action={action}",
                client_id=client_id,
                action=action_name,
            )
            return {"success": False, "error": "No CRM contact linked to this client."}

        deal = await deal_repository(
            db, organization_id=organization_id
        ).get_latest_open_for_contact(contact.id)
        if deal is None:
            logger.info(
                "CrmBridge.no_open_deal | client_id={client_id} contact_id={contact_id} action={action}",
                client_id=client_id,
                contact_id=contact.id,
                action=action_name,
            )
            return {"success": False, "error": "No open deal for contact."}

        try:
            if action_name == "move_stage":
                return await self._move_stage(db, organization_id, deal.id, params)
            if action_name == "add_note":
                return await self._add_note(db, organization_id, deal.id, contact.id, params)
            return await self._add_tag(db, organization_id, deal.id, params)
        except (DealServiceError, NoteServiceError, TagServiceError) as exc:
            return {"success": False, "error": exc.message, "status_code": exc.status_code}
        except (ValueError, KeyError, TypeError) as exc:
            return {"success": False, "error": str(exc)}

    async def _resolve_contact(
        self,
        db: AsyncSession,
        client_id: uuid.UUID,
    ) -> tuple[uuid.UUID | None, Any]:
        stmt = (
            select(Client)
            .where(Client.id == client_id)
            .options(joinedload(Client.bot))
        )
        result = await db.execute(stmt)
        client = result.scalar_one_or_none()
        if client is None or client.bot is None or client.bot.organization_id is None:
            return None, None

        organization_id = uuid.UUID(str(client.bot.organization_id))
        contact = await contact_repository(
            db, organization_id=organization_id
        ).get_by_linked_client_id(client_id)
        return organization_id, contact

    async def _move_stage(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        stage_raw = params.get("stage_id")
        if not stage_raw:
            raise ValueError("params.stage_id is required for move_stage.")
        stage_id = uuid.UUID(str(stage_raw))
        deal = await deal_service.move_stage(db, organization_id, deal_id, stage_id)
        return {
            "success": True,
            "action": "move_stage",
            "deal_id": str(deal.id),
            "stage_id": str(deal.stage_id),
        }

    async def _add_note(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        contact_id: uuid.UUID,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("params.text is required for add_note.")
        note = await note_service.create_note(
            db,
            organization_id,
            CrmNoteCreate(text=text, deal_id=deal_id, contact_id=contact_id),
        )
        return {
            "success": True,
            "action": "add_note",
            "note_id": str(note.id),
            "deal_id": str(deal_id),
        }

    async def _add_tag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        tag_raw = params.get("tag_id")
        if not tag_raw:
            raise ValueError("params.tag_id is required for add_tag.")
        tag_id = uuid.UUID(str(tag_raw))
        tag = await tag_service.attach_tag_to_deal(db, organization_id, deal_id, tag_id)
        return {
            "success": True,
            "action": "add_tag",
            "tag_id": str(tag.id),
            "deal_id": str(deal_id),
        }


crm_bridge_service = CrmBridgeService()

# Re-export DealStatus for tests / callers that introspect bridge helpers.
__all__ = ["CrmBridgeService", "CrmBridgeServiceError", "crm_bridge_service", "DealStatus"]
