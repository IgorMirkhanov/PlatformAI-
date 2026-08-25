"""Bitrix24 inbound events — verify application_token, ACK 200, enqueue."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request, Response, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_hub import IntegrationConnection
from app.models.tenant_credentials import TenantCredential
from app.repositories.credentials_repository import CredentialsRepository
from app.services.crypto_service import decrypt_payload
from app.services.integration_hub.adapters.bitrix24 import (
    flatten_form_dict,
    parse_bitrix_webhook,
    verify_application_token,
)
from app.services.integration_hub.oauth import secrets_from_connection_with_vault
from app.services.webhook_processor import enqueue_if_needed, process_hub_inbound_event


async def _form_payload(request: Request) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    raw = await request.body()
    if "json" in content_type:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    try:
        form = await request.form()
    except Exception:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    flat: dict[str, Any] = {}
    for key, value in form.items():
        flat[str(key)] = "" if hasattr(value, "filename") else str(value)
    return flatten_form_dict(flat)


async def _persist_application_token(
    db: AsyncSession,
    connection: IntegrationConnection,
    token: str,
) -> None:
    if connection.credential_id is None or not token:
        return
    cred = await db.scalar(
        select(TenantCredential).where(TenantCredential.id == connection.credential_id)
    )
    if cred is None:
        return
    payload = decrypt_payload(
        cred.encrypted_payload,
        cred.encryption_iv,
        cred.encryption_tag,
        key_version=int(cred.key_version),
    )
    payload["application_token"] = token
    kind = cred.kind if isinstance(cred.kind, str) else str(cred.kind)
    await CredentialsRepository(db).upsert(
        organization_id=connection.organization_id,
        kind=kind,
        payload=payload,
        label=cred.label,
        oauth_expires_at=cred.oauth_expires_at,
        status=cred.status,
    )


async def ingest_bitrix24_webhook(
    *,
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession,
) -> Response:
    payload = await _form_payload(request)
    parsed = parse_bitrix_webhook(payload)
    connection = await db.get(IntegrationConnection, connection_id)
    if connection is None or connection.provider != "bitrix24":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        secrets = await secrets_from_connection_with_vault(db, connection)
        stored_token = str((secrets.extra or {}).get("application_token") or "") or None
    except Exception:
        logger.warning("Bitrix24.webhook_secrets_unreadable | connection_id={id}", id=connection_id)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    provided = str(parsed.get("application_token") or "")
    event_key = str(parsed.get("event") or "").upper()
    if stored_token:
        if not verify_application_token(stored=stored_token, provided=provided):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    else:
        if not provided:
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        expected_member = str(
            (connection.config_json or {}).get("member_id") or connection.external_account_id or ""
        )
        got_member = str(parsed.get("member_id") or "")
        if expected_member and got_member and expected_member != got_member:
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        if not expected_member and event_key != "ONAPPINSTALL":
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        await _persist_application_token(db, connection, provided)

    external_event_id = (
        f"{connection_id}:{parsed.get('event')}:{parsed.get('entity_id')}:{parsed.get('ts')}"
    )
    result = await process_hub_inbound_event(
        db,
        connection=connection,
        provider="bitrix24",
        external_event_id=external_event_id,
        payload=dict(payload),
    )
    await db.commit()
    enqueue_if_needed(result)
    return Response(status_code=status.HTTP_200_OK)
