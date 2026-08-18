"""CRM repository package."""

from app.repositories.crm.account_repository import AccountRepository, account_repository
from app.repositories.crm.activity_repository import ActivityRepository, activity_repository
from app.repositories.crm.api_key_repository import (
    ApiKeyRepository,
    api_key_repository,
    get_active_api_key_by_hash,
)
from app.repositories.crm.automation_rule_repository import (
    AutomationRuleRepository,
    automation_rule_repository,
)
from app.repositories.crm.base_crm_repository import BaseCrmRepository
from app.repositories.crm.contact_repository import ContactRepository, contact_repository
from app.repositories.crm.custom_field_repository import (
    CustomFieldRepository,
    custom_field_repository,
)
from app.repositories.crm.deal_repository import DealRepository, deal_repository
from app.repositories.crm.note_repository import NoteRepository, note_repository
from app.repositories.crm.pipeline_repository import PipelineRepository, pipeline_repository
from app.repositories.crm.setting_repository import SettingRepository, setting_repository
from app.repositories.crm.stage_repository import StageRepository, stage_repository
from app.repositories.crm.tag_repository import TagRepository, tag_repository
from app.repositories.crm.timeline_repository import TimelineRepository, timeline_repository

__all__ = [
    "AccountRepository",
    "ActivityRepository",
    "ApiKeyRepository",
    "AutomationRuleRepository",
    "BaseCrmRepository",
    "ContactRepository",
    "CustomFieldRepository",
    "DealRepository",
    "NoteRepository",
    "PipelineRepository",
    "SettingRepository",
    "StageRepository",
    "TagRepository",
    "TimelineRepository",
    "account_repository",
    "activity_repository",
    "api_key_repository",
    "automation_rule_repository",
    "contact_repository",
    "custom_field_repository",
    "deal_repository",
    "get_active_api_key_by_hash",
    "note_repository",
    "pipeline_repository",
    "setting_repository",
    "stage_repository",
    "tag_repository",
    "timeline_repository",
]
