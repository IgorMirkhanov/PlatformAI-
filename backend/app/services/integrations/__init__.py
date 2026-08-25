"""Integration service modules (Google Calendar, CRM, Kaspi, support webhooks)."""

from app.services.integrations.crm_service import create_amocrm_lead, get_deal_status, save_lead_to_crm_integration
from app.services.integrations.google_calendar_service import (
    build_google_auth_url,
    check_calendar_availability,
    create_calendar_event,
    decode_oauth_state,
    exchange_google_code,
    get_valid_google_token,
    persist_google_tokens,
)
from app.services.integrations.kaspi_service import (
    create_kaspi_invoice,
    verify_kaspi_receipt_bytes,
    verify_kaspi_receipt_text,
)
from app.services.integrations.support_service import (
    create_uon_travel_lead,
    dispatch_custom_webhook,
    transfer_jivo_to_operator,
)

__all__ = [
    "build_google_auth_url",
    "check_calendar_availability",
    "create_amocrm_lead",
    "create_calendar_event",
    "create_kaspi_invoice",
    "create_uon_travel_lead",
    "decode_oauth_state",
    "dispatch_custom_webhook",
    "exchange_google_code",
    "get_deal_status",
    "get_valid_google_token",
    "persist_google_tokens",
    "save_lead_to_crm_integration",
    "transfer_jivo_to_operator",
    "verify_kaspi_receipt_bytes",
    "verify_kaspi_receipt_text",
]
