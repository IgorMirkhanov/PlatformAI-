from fastapi import APIRouter

from app.api.endpoints.admin import router as admin_router
from app.api.endpoints.ai_prompts import router as ai_prompts_router
from app.api.endpoints.analytics import router as analytics_router
from app.api.endpoints.auth import router as auth_router
from app.api.endpoints.billing.invites import router as organization_invites_router
from app.api.endpoints.billing.subscriptions import router as billing_router
from app.api.endpoints.billing_stripe import router as billing_stripe_router
from app.api.endpoints.bot_knowledge import router as bot_knowledge_router
from app.api.endpoints.bot_management import router as bot_management_router
from app.api.endpoints.bots import router as bots_lifecycle_router
from app.api.endpoints.channels import router as channels_hub_router
from app.api.endpoints.chat import router as chat_router
from app.api.endpoints.chats import router as chats_router
from app.api.endpoints.crm_integrations import router as crm_integrations_router
from app.api.endpoints.bot_app_integrations import router as bot_app_integrations_router
from app.api.endpoints.integrations.db_connections import router as db_connections_router
from app.api.endpoints.integrations.google_oauth import router as google_oauth_router
from app.api.endpoints.security.audit_logs import router as security_audit_logs_router
from app.api.endpoints.dashboard import router as dashboard_router
from app.api.endpoints.flow_execution import router as flow_execution_router
from app.api.endpoints.flow.flows import router as flows_crud_router
from app.api.endpoints.flow_versions import router as flow_versions_router
from app.api.endpoints.health_check import router as health_check_router
from app.api.endpoints.knowledge_base import router as knowledge_base_router
from app.api.endpoints.knowledge import router as knowledge_router
from app.api.endpoints.llm_models import router as llm_models_router
from app.api.endpoints.llm.prompts import router as llm_prompts_router
from app.api.endpoints.llm.rag import router as llm_knowledge_router
from app.api.endpoints.omnichannel.whatsapp import router as omnichannel_whatsapp_router
from app.api.endpoints.omnichannel.telegram import router as omnichannel_telegram_router
from app.api.endpoints.sandbox import router as sandbox_router
from app.api.endpoints.test_chat import router as test_chat_router
from app.api.endpoints.system import router as system_router
from app.api.endpoints.team import router as team_router
from app.api.endpoints.webhooks import router as webhooks_router
from app.api.endpoints.wazzup_webhook import router as wazzup_webhook_router
from app.api.endpoints.wallet import router as wallet_router
from app.api.endpoints.credentials import router as credentials_router
from app.api.endpoints.integration_hub import (
    oauth_router as integration_oauth_router,
    router as integration_hub_router,
)
from app.api.endpoints.playground import router as playground_router
from app.api.endpoints.whatsapp import router as whatsapp_router
from app.api.routers.auth import router as auth_extensions_router
from app.api.routers.bots import router as bots_list_router
from app.api.routers.bots import saas_router as saas_bots_router
from app.api.endpoints.organizations import router as organizations_router
from app.api.endpoints.organization_keys import router as organization_keys_router
from app.api.endpoints.crm import (
    accounts_router as crm_accounts_router,
    activities_router as crm_activities_router,
    analytics_router as crm_analytics_router,
    api_keys_router as crm_api_keys_router,
    automations_router as crm_automations_router,
    contacts_router as crm_contacts_router,
    custom_fields_router as crm_custom_fields_router,
    deals_router as crm_deals_router,
    notes_router as crm_notes_router,
    pipelines_router as crm_pipelines_router,
    public_webhooks_router as crm_public_webhooks_router,
    tags_router as crm_tags_router,
    timeline_router as crm_timeline_router,
    webhooks_router as crm_webhooks_router,
)
from app.api.websockets.operator_ws import router as operator_ws_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(auth_extensions_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(organization_keys_router)
api_v1_router.include_router(organization_invites_router)
api_v1_router.include_router(bots_list_router)
api_v1_router.include_router(saas_bots_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(team_router)
api_v1_router.include_router(webhooks_router)
api_v1_router.include_router(wazzup_webhook_router)
api_v1_router.include_router(knowledge_base_router)
api_v1_router.include_router(knowledge_router)
api_v1_router.include_router(llm_models_router)
api_v1_router.include_router(llm_prompts_router)
api_v1_router.include_router(llm_knowledge_router)
api_v1_router.include_router(ai_prompts_router)
api_v1_router.include_router(omnichannel_whatsapp_router)
api_v1_router.include_router(omnichannel_telegram_router)
api_v1_router.include_router(channels_hub_router)
api_v1_router.include_router(whatsapp_router)
api_v1_router.include_router(bot_management_router)
api_v1_router.include_router(bots_lifecycle_router)
api_v1_router.include_router(bot_knowledge_router)
api_v1_router.include_router(flows_crud_router)
api_v1_router.include_router(flow_versions_router)
api_v1_router.include_router(flow_execution_router)
api_v1_router.include_router(crm_integrations_router)
api_v1_router.include_router(bot_app_integrations_router)
api_v1_router.include_router(db_connections_router)
api_v1_router.include_router(google_oauth_router)
api_v1_router.include_router(integration_oauth_router)
api_v1_router.include_router(security_audit_logs_router)
api_v1_router.include_router(crm_pipelines_router)
api_v1_router.include_router(crm_accounts_router)
api_v1_router.include_router(crm_contacts_router)
api_v1_router.include_router(crm_deals_router)
api_v1_router.include_router(crm_activities_router)
api_v1_router.include_router(crm_notes_router)
api_v1_router.include_router(crm_timeline_router)
api_v1_router.include_router(crm_tags_router)
api_v1_router.include_router(crm_custom_fields_router)
api_v1_router.include_router(crm_automations_router)
api_v1_router.include_router(crm_api_keys_router)
api_v1_router.include_router(crm_public_webhooks_router)
api_v1_router.include_router(crm_analytics_router)
api_v1_router.include_router(crm_webhooks_router)
api_v1_router.include_router(billing_router)
api_v1_router.include_router(billing_stripe_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(health_check_router)
api_v1_router.include_router(system_router)
api_v1_router.include_router(chats_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(sandbox_router)
api_v1_router.include_router(test_chat_router)
api_v1_router.include_router(wallet_router)
api_v1_router.include_router(credentials_router)
api_v1_router.include_router(integration_hub_router)
api_v1_router.include_router(playground_router)
api_v1_router.include_router(operator_ws_router)
