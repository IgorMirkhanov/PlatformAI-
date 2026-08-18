"""Native CRM models package."""

from app.models.crm.account import CrmAccount
from app.models.crm.activity import ActivityType, CrmActivity
from app.models.crm.api_key import CrmApiKey
from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.models.crm.contact import CrmContact
from app.models.crm.custom_field import CrmCustomFieldDefinition, CrmEntityType, CrmFieldType
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.note import CrmNote
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.setting import CrmSetting
from app.models.crm.stage import CrmStage
from app.models.crm.tag import CrmTag, crm_deal_tags
from app.models.crm.timeline_event import CrmTimelineEvent
from app.models.crm.webhook_subscription import CrmWebhookSubscription

__all__ = [
    "ActivityType",
    "AutomationTriggerType",
    "CrmAccount",
    "CrmActivity",
    "CrmApiKey",
    "CrmAutomationRule",
    "CrmContact",
    "CrmCustomFieldDefinition",
    "CrmDeal",
    "CrmEntityType",
    "CrmFieldType",
    "CrmNote",
    "CrmPipeline",
    "CrmSetting",
    "CrmStage",
    "CrmTag",
    "CrmTimelineEvent",
    "CrmWebhookSubscription",
    "DealStatus",
    "crm_deal_tags",
]
