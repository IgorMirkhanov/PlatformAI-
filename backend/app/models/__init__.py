from app.models.core_models import (
    Bot,
    BotDiagnosticLog,
    BotFlow,
    ChatMessage,
    Client,
    Company,
    DiagnosticErrorType,
    KnowledgeBase,
    KnowledgeBaseDocument,
    KnowledgeDocumentStatus,
    MessageSender,
    Organization,
    PlatformType,
    Project,
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
    Subscription,
    SubscriptionPlanName,
    SubscriptionStatus,
    SystemNotification,
    SystemNotificationCategory,
    SystemNotificationSeverity,
    TeamInvitation,
    TeamInvitationStatus,
    UserCompanyWorkspace,
    UserRole,
)
from app.models.users import User
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.models.admin_audit import AdminAuditLog
from app.models.flow import Edge, Flow, Node
from app.models.usage import LLMUsageLog
from app.models.saas_metering import (
    BotFlowRevision,
    BotFlowVersion,
    ModerationAction,
    ModerationEvent,
    ProcessedStripeEvent,
    StripeCustomer,
    StripeCustomerLink,
    UsageEvent,
    UsageMetricType,
)
from app.models.auth_tokens import OAuthAccount, PasswordResetToken, RefreshToken
from app.models.integration import Integration, IntegrationProvider, IntegrationStatus
from app.models.integrations import OrganizationDbConnection
from app.models.tenant_credentials import (
    CredentialKind,
    CredentialStatus,
    TenantCredential,
    WebhookEventLog,
)
from app.models.integration_hub import (
    AgentActionStatus,
    HubAuthType,
    HubConnectionStatus,
    HubProvider,
    IntegrationAgentAction,
    IntegrationConnection,
    IntegrationOAuthApp,
    IntegrationProvider,
    IntegrationUsageEvent,
    IntegrationWebhookEvent,
    WebhookEventStatus,
)
from app.models.llm_model import LLMModel
from app.models.organization_api_key import OrganizationApiKey
from app.models.security.audit_log import AuditLog as SecurityAuditLog
from app.models.crm import (
    ActivityType,
    AutomationTriggerType,
    CrmAccount,
    CrmActivity,
    CrmApiKey,
    CrmAutomationRule,
    CrmContact,
    CrmCustomFieldDefinition,
    CrmDeal,
    CrmEntityType,
    CrmFieldType,
    CrmNote,
    CrmPipeline,
    CrmSetting,
    CrmStage,
    CrmTag,
    CrmTimelineEvent,
    CrmWebhookSubscription,
    DealStatus,
)
from app.models.billing import CreditTransaction, OrganizationInvite, OrganizationWallet
from app.models.billing import (
    OrganizationSubscription,
    PaymentInvoice,
)
from app.models.llm import PromptTemplate
from app.models.llm.knowledge import (
    KnowledgeBase as LlmKnowledgeBase,
    KnowledgeDocument as LlmKnowledgeDocument,
)
from app.models.omnichannel import OmnichannelMessageLog

# Register AES credential descriptors on Bot (telegram_bot_token property).
import app.models.bot  # noqa: E402, F401
import app.models.channels  # noqa: E402, F401
import app.models.integrations  # noqa: E402, F401
import app.models.flow  # noqa: E402, F401
import app.models.saas_metering  # noqa: E402, F401
import app.models.usage  # noqa: E402, F401
import app.models.auth_tokens  # noqa: E402, F401
import app.models.integration  # noqa: E402, F401
import app.models.tenant_credentials  # noqa: E402, F401
import app.models.integration_hub  # noqa: E402, F401
import app.models.organization_api_key  # noqa: E402, F401
import app.models.crm  # noqa: E402, F401
import app.models.billing  # noqa: E402, F401
import app.models.wallet  # noqa: E402, F401
import app.models.operator_notification  # noqa: E402, F401
import app.models.llm  # noqa: E402, F401
import app.models.omnichannel  # noqa: E402, F401

__all__ = [
    "ActivityType",
    "AutomationTriggerType",
    "Bot",
    "BotChannel",
    "BotDiagnosticLog",
    "BotFlow",
    "BotFlowRevision",
    "BotFlowVersion",
    "ChatMessage",
    "Client",
    "Company",
    "CreditTransaction",
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
    "Organization",
    "OrganizationInvite",
    "OrganizationWallet",
    "OmnichannelMessageLog",
    "LlmKnowledgeBase",
    "LlmKnowledgeDocument",
    "PromptTemplate",
    "Project",
    "DiagnosticErrorType",
    "HubChannelStatus",
    "HubChannelType",
    "KnowledgeBase",
    "KnowledgeBaseDocument",
    "KnowledgeDocumentStatus",
    "MessageSender",
    "PlatformType",
    "BillingTransaction",
    "BillingTransactionStatus",
    "BillingTransactionType",
    "Subscription",
    "SubscriptionPlanName",
    "SubscriptionStatus",
    "SystemNotification",
    "SystemNotificationCategory",
    "SystemNotificationSeverity",
    "TeamInvitation",
    "TeamInvitationStatus",
    "UserCompanyWorkspace",
    "UserRole",
    "User",
    "AdminAuditLog",
    "SecurityAuditLog",
    "LLMUsageLog",
    "Flow",
    "Node",
    "Edge",
    "UsageEvent",
    "UsageMetricType",
    "StripeCustomer",
    "StripeCustomerLink",
    "ModerationEvent",
    "ModerationAction",
    "ProcessedStripeEvent",
    "RefreshToken",
    "PasswordResetToken",
    "OAuthAccount",
    "Integration",
    "IntegrationProvider",
    "IntegrationStatus",
    "OrganizationDbConnection",
    "TenantCredential",
    "WebhookEventLog",
    "CredentialKind",
    "CredentialStatus",
    "AgentActionStatus",
    "HubAuthType",
    "HubConnectionStatus",
    "HubProvider",
    "IntegrationAgentAction",
    "IntegrationConnection",
    "IntegrationOAuthApp",
    "IntegrationProvider",
    "IntegrationUsageEvent",
    "IntegrationWebhookEvent",
    "WebhookEventStatus",
    "OrganizationApiKey",
    "LLMModel",
]
