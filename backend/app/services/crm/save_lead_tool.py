"""Built-in LLM tool: persist a lead in Bitrix24 CRM."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot, Client
from app.utils.phone_utils import clean_phone_number


# Bitrix24 SOURCE_ID values from the standard CRM dictionary.
_BITRIX_SOURCE_BY_CHANNEL: dict[str, str] = {
    "telegram": "OTHER",
    "whatsapp": "OTHER",
    "web": "WEB",
    "wazzup": "OTHER",
}


async def save_lead_to_crm(
    db: AsyncSession,
    *,
    bot: Bot,
    client: Client | None = None,
    phone: str | None = None,
    client_name: str | None = None,
    channel: str = "web",
    channel_user_id: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """
    Create or update a Bitrix24 lead/contact.

    Returns a structured dict the LLM can read — never raises on CRM errors.
    """
    from app.models.integrations import reveal_bitrix_config
    from app.services.crm_orchestrator import crm_orchestrator

    webhook = crm_orchestrator._get_bitrix_webhook(bot)
    if not webhook:
        return {
            "status": "error",
            "reason": "crm_not_connected",
            "message": "Bitrix24 не подключён для этого бота.",
        }

    cleaned_phone = clean_phone_number(phone)
    if phone and not cleaned_phone:
        return {
            "status": "error",
            "reason": "invalid_phone",
            "message": "Номер телефона указан неверно или отсутствует.",
        }

    identity = channel_user_id or (client.external_id if client else None) or cleaned_phone or ""
    display_name = (client_name or "").strip() or (
        (client.first_name if client else None) or "Клиент"
    )
    source_id = _BITRIX_SOURCE_BY_CHANNEL.get(str(channel).lower(), "OTHER")
    title = f"Лид из {channel}: {cleaned_phone or identity}"

    fields: dict[str, Any] = {
        "TITLE": title,
        "NAME": display_name,
        "SOURCE_ID": source_id,
    }
    if cleaned_phone:
        fields["PHONE"] = [{"VALUE": cleaned_phone, "VALUE_TYPE": "WORK"}]
    if comment:
        fields["COMMENTS"] = comment[:2000]

    payload_sent = {"fields": fields}

    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            # Prefer lead when no phone — contact requires PHONE in many Bitrix portals.
            if cleaned_phone:
                contact_id = await crm_orchestrator._bitrix_find_or_create_contact_safe(
                    http,
                    webhook,
                    name=display_name,
                    phone=cleaned_phone,
                    external_id=str(identity),
                    payload_sent=payload_sent,
                )
                if contact_id is None:
                    return {
                        "status": "error",
                        "reason": "invalid_phone",
                        "message": "Номер телефона указан неверно или отсутствует.",
                    }
                lead_fields = {**fields, "CONTACT_ID": contact_id}
                lead_id = await crm_orchestrator._bitrix_api_add(
                    http,
                    webhook,
                    "crm.lead.add",
                    {"fields": lead_fields},
                )
            else:
                lead_id = await crm_orchestrator._bitrix_api_add(
                    http,
                    webhook,
                    "crm.lead.add",
                    payload_sent,
                )

        logger.info(
            "save_lead_to_crm.success | bot_id={bot_id} lead_id={lead_id} channel={channel}",
            bot_id=bot.id,
            lead_id=lead_id,
            channel=channel,
        )
        return {
            "status": "ok",
            "lead_id": lead_id,
            "phone": cleaned_phone,
            "message": "Лид успешно сохранён в Bitrix24.",
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body = exc.response.text[:2000]
        logger.error(
            "Bitrix24.payload_sent | endpoint={endpoint} payload={payload}",
            endpoint="crm.lead.add",
            payload=payload_sent,
        )
        logger.error(
            "Bitrix24.error_response | status={status} body={body}",
            status=status,
            body=body,
        )
        if status in {400, 422} and not cleaned_phone:
            return {
                "status": "error",
                "reason": "invalid_phone",
                "message": "Номер телефона указан неверно или отсутствует.",
            }
        return {
            "status": "error",
            "reason": "bitrix_api_error",
            "message": f"Bitrix24 вернул ошибку {status}. Проверьте данные и попробуйте снова.",
        }
    except Exception as exc:
        logger.exception(
            "save_lead_to_crm.failed | bot_id={bot_id} error={error}",
            bot_id=bot.id,
            error=str(exc),
        )
        return {
            "status": "error",
            "reason": "internal_error",
            "message": "Не удалось сохранить лид. Попробуйте позже.",
        }
