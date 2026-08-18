"""CRM services package."""

from app.services.crm.account_service import AccountService, AccountServiceError, account_service
from app.services.crm.activity_service import ActivityService, ActivityServiceError, activity_service
from app.services.crm.api_key_service import ApiKeyService, ApiKeyServiceError, api_key_service
from app.services.crm.automation_evaluator_service import (
    AutomationEvaluatorService,
    automation_evaluator_service,
)
from app.services.crm.automation_executor_service import (
    AutomationExecutorService,
    automation_executor_service,
)
from app.services.crm.automation_rule_service import (
    AutomationRuleService,
    AutomationRuleServiceError,
    automation_rule_service,
)
from app.services.crm.contact_service import ContactService, ContactServiceError, contact_service
from app.services.crm.crm_bridge_service import CrmBridgeService, CrmBridgeServiceError, crm_bridge_service
from app.services.crm.custom_field_service import (
    CustomFieldService,
    CustomFieldServiceError,
    custom_field_service,
)
from app.services.crm.deal_service import DealService, DealServiceError, deal_service
from app.services.crm.inbound_lead_service import (
    InboundLeadService,
    InboundLeadServiceError,
    inbound_lead_service,
)
from app.services.crm.note_service import NoteService, NoteServiceError, note_service
from app.services.crm.pipeline_service import PipelineService, PipelineServiceError, pipeline_service
from app.services.crm.setting_service import SettingService, SettingServiceError, setting_service
from app.services.crm.tag_service import TagService, TagServiceError, tag_service
from app.services.crm.timeline_service import TimelineService, TimelineServiceError, timeline_service

__all__ = [
    "AccountService",
    "AccountServiceError",
    "ActivityService",
    "ActivityServiceError",
    "ApiKeyService",
    "ApiKeyServiceError",
    "AutomationEvaluatorService",
    "AutomationExecutorService",
    "AutomationRuleService",
    "AutomationRuleServiceError",
    "ContactService",
    "ContactServiceError",
    "CrmBridgeService",
    "CrmBridgeServiceError",
    "CustomFieldService",
    "CustomFieldServiceError",
    "DealService",
    "DealServiceError",
    "InboundLeadService",
    "InboundLeadServiceError",
    "NoteService",
    "NoteServiceError",
    "PipelineService",
    "PipelineServiceError",
    "SettingService",
    "SettingServiceError",
    "TagService",
    "TagServiceError",
    "TimelineService",
    "TimelineServiceError",
    "account_service",
    "activity_service",
    "api_key_service",
    "automation_evaluator_service",
    "automation_executor_service",
    "automation_rule_service",
    "contact_service",
    "crm_bridge_service",
    "custom_field_service",
    "deal_service",
    "inbound_lead_service",
    "note_service",
    "pipeline_service",
    "setting_service",
    "tag_service",
    "timeline_service",
]
