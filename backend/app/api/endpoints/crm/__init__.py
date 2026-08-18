"""CRM API endpoints package."""

from app.api.endpoints.crm.accounts import router as accounts_router
from app.api.endpoints.crm.activities import router as activities_router
from app.api.endpoints.crm.analytics import router as analytics_router
from app.api.endpoints.crm.api_keys import router as api_keys_router
from app.api.endpoints.crm.automations import router as automations_router
from app.api.endpoints.crm.contacts import router as contacts_router
from app.api.endpoints.crm.custom_fields import router as custom_fields_router
from app.api.endpoints.crm.deals import router as deals_router
from app.api.endpoints.crm.notes import router as notes_router
from app.api.endpoints.crm.pipelines import router as pipelines_router
from app.api.endpoints.crm.public_webhooks import router as public_webhooks_router
from app.api.endpoints.crm.tags import router as tags_router
from app.api.endpoints.crm.timeline import router as timeline_router
from app.api.endpoints.crm.webhooks import router as webhooks_router

__all__ = [
    "accounts_router",
    "activities_router",
    "analytics_router",
    "api_keys_router",
    "automations_router",
    "contacts_router",
    "custom_fields_router",
    "deals_router",
    "notes_router",
    "pipelines_router",
    "public_webhooks_router",
    "tags_router",
    "timeline_router",
    "webhooks_router",
]
