"""Public inbound lead capture for CRM API keys."""

from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.pipeline_repository import pipeline_repository
from app.schemas.crm.accounts_contacts import CrmContactCreate
from app.schemas.crm.api_keys import InboundLeadCreate, InboundLeadResponse
from app.schemas.crm.deals import CrmDealCreate
from app.services.crm.contact_service import ContactServiceError, contact_service
from app.services.crm.deal_service import DealServiceError, deal_service


class InboundLeadServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InboundLeadService:
    async def ingest(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: InboundLeadCreate,
    ) -> InboundLeadResponse:
        contact, created = await self._find_or_create_contact(db, organization_id, payload)
        pipeline_id, stage_id = await self._resolve_funnel(
            db,
            organization_id,
            pipeline_id=payload.pipeline_id,
            stage_id=payload.stage_id,
        )
        title = (payload.deal_title or f"Lead: {payload.first_name}").strip()
        try:
            deal = await deal_service.create_deal(
                db,
                organization_id,
                CrmDealCreate(
                    title=title,
                    pipeline_id=pipeline_id,
                    stage_id=stage_id,
                    contact_id=contact.id,
                    source=payload.source or "api",
                    custom_fields=dict(payload.custom_fields or {}),
                ),
            )
        except DealServiceError as exc:
            raise InboundLeadServiceError(exc.message, status_code=exc.status_code) from exc

        logger.info(
            "CRM.inbound_lead | org={org} contact_id={contact_id} deal_id={deal_id} created={created}",
            org=organization_id,
            contact_id=contact.id,
            deal_id=deal.id,
            created=created,
        )
        return InboundLeadResponse(
            contact_id=contact.id,
            deal_id=deal.id,
            organization_id=organization_id,
            contact_created=created,
            deal_title=deal.title,
        )

    async def _find_or_create_contact(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: InboundLeadCreate,
    ):
        contacts = contact_repository(db, organization_id=organization_id)
        existing = await contacts.find_by_phone_or_email(
            phone=payload.phone,
            email=payload.email,
        )
        if existing is not None:
            return existing, False
        try:
            created = await contact_service.create_contact(
                db,
                organization_id,
                CrmContactCreate(
                    first_name=payload.first_name,
                    phone=payload.phone,
                    email=payload.email,
                    source=payload.source or "api",
                    custom_fields=dict(payload.custom_fields or {}),
                ),
            )
        except ContactServiceError as exc:
            raise InboundLeadServiceError(exc.message, status_code=exc.status_code) from exc
        row = await contacts.get(created.id)
        assert row is not None
        return row, True

    async def _resolve_funnel(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        pipeline_id: uuid.UUID | None,
        stage_id: uuid.UUID | None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        pipelines = pipeline_repository(db, organization_id=organization_id)
        if pipeline_id is not None and stage_id is not None:
            pipeline = await pipelines.get_with_stages(pipeline_id)
            if pipeline is None:
                raise InboundLeadServiceError("Pipeline not found.", status_code=404)
            stage_ids = {s.id for s in (pipeline.stages or [])}
            if stage_id not in stage_ids:
                raise InboundLeadServiceError(
                    "stage_id does not belong to the given pipeline.",
                    status_code=400,
                )
            return pipeline_id, stage_id

        pipeline = None
        if pipeline_id is not None:
            pipeline = await pipelines.get_with_stages(pipeline_id)
            if pipeline is None:
                raise InboundLeadServiceError("Pipeline not found.", status_code=404)
        else:
            pipeline = await pipelines.get_default()
            if pipeline is None:
                listed = await pipelines.list_with_stages(limit=1)
                pipeline = listed[0] if listed else None
        if pipeline is None or not pipeline.stages:
            raise InboundLeadServiceError(
                "No CRM pipeline with stages configured for this organization.",
                status_code=400,
            )
        if stage_id is not None:
            stage_ids = {s.id for s in pipeline.stages}
            if stage_id not in stage_ids:
                raise InboundLeadServiceError(
                    "stage_id does not belong to the resolved pipeline.",
                    status_code=400,
                )
            return pipeline.id, stage_id
        first_stage = sorted(pipeline.stages, key=lambda s: s.position)[0]
        return pipeline.id, first_stage.id


inbound_lead_service = InboundLeadService()
