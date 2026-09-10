import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.channels import BotChannel
    from app.models.flow import Flow
    from app.models.users import User


class PlatformType(str, enum.Enum):
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    INSTAGRAM = "INSTAGRAM"
    VKONTAKTE = "VKONTAKTE"
    WEB_WIDGET = "WEB_WIDGET"


class MessageSender(str, enum.Enum):
    CLIENT = "CLIENT"
    BOT = "BOT"
    OPERATOR = "OPERATOR"


class SubscriptionPlanName(str, enum.Enum):
    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class BillingTransactionType(str, enum.Enum):
    TOP_UP = "TOP_UP"
    SUBSCRIPTION_CHARGE = "SUBSCRIPTION_CHARGE"
    LLM_DEDUCTION = "LLM_DEDUCTION"
    BONUS = "BONUS"
    REFUND = "REFUND"
    MANUAL_DEPOSIT = "MANUAL_DEPOSIT"
    CARD_DEPOSIT = "CARD_DEPOSIT"


class BillingTransactionStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    FAILED = "FAILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SystemNotificationSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SystemNotificationCategory(str, enum.Enum):
    BILLING_DEPOSIT = "BILLING_DEPOSIT"
    SYSTEM = "SYSTEM"


class UserRole(str, enum.Enum):
    """
    Workspace RBAC roles.

    SaaS shorthand:
      - owner  → OWNER
      - admin  → ADMIN
      - member → MEMBER | PROMPT_ENGINEER (flow collaborators)
      - operator → OPERATOR (inbox / CRM operators)
    """

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    PROMPT_ENGINEER = "PROMPT_ENGINEER"
    OPERATOR = "OPERATOR"

    @classmethod
    def member_roles(cls) -> frozenset["UserRole"]:
        return frozenset({cls.MEMBER, cls.PROMPT_ENGINEER, cls.OPERATOR})

    @property
    def is_member(self) -> bool:
        return self in self.member_roles()


class TeamInvitationStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class DiagnosticErrorType(str, enum.Enum):
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_EXECUTION_FAILURE = "LLM_EXECUTION_FAILURE"
    RAG_EMPTY = "RAG_EMPTY"
    CRM_DISCONNECT = "CRM_DISCONNECT"
    CRM_INTEGRATION_ERROR = "CRM_INTEGRATION_ERROR"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    GOOGLE_SYNC_FAILED = "GOOGLE_SYNC_FAILED"
    MESSENGER_API_ERROR = "MESSENGER_API_ERROR"


DEFAULT_SCHEDULE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "timezone": "Asia/Almaty",
    "windows": [],
}


class Subscription(Base):
    """SaaS billing subscription linked to a platform user."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_name: Mapped[SubscriptionPlanName] = mapped_column(
        Enum(SubscriptionPlanName, name="subscription_plan_name"),
        nullable=False,
        default=SubscriptionPlanName.FREE,
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    transactions: Mapped[list["BillingTransaction"]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BillingTransaction(Base):
    """Immutable ledger entry for subscription balance movements."""

    __tablename__ = "billing_transactions"
    __table_args__ = (
        Index(
            "uq_billing_transactions_reference_id",
            "reference_id",
            unique=True,
            postgresql_where=text("reference_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_type: Mapped[BillingTransactionType] = mapped_column(
        Enum(BillingTransactionType, name="billing_transaction_type"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KZT")
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    receipt_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[BillingTransactionStatus] = mapped_column(
        Enum(BillingTransactionStatus, name="billing_transaction_status"),
        nullable=False,
        default=BillingTransactionStatus.SUCCESS,
    )
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    subscription: Mapped["Subscription | None"] = relationship(back_populates="transactions")
    user: Mapped["User"] = relationship(back_populates="billing_transactions")


class SystemNotification(Base):
    """Global admin alert ledger (billing deposits, platform events)."""

    __tablename__ = "system_notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[SystemNotificationCategory] = mapped_column(
        Enum(SystemNotificationCategory, name="system_notification_category"),
        nullable=False,
        index=True,
    )
    severity: Mapped[SystemNotificationSeverity] = mapped_column(
        Enum(SystemNotificationSeverity, name="system_notification_severity"),
        nullable=False,
        default=SystemNotificationSeverity.INFO,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class Bot(Base):
    """Bot instance (AI agent) owned by a user within an Organization / Project."""

    __tablename__ = "bots"
    __table_args__ = (
        Index("ix_bots_organization_id_is_active", "organization_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Multi-tenancy: Organization == companies row; Project is optional grouping.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_type: Mapped[PlatformType] = mapped_column(
        Enum(PlatformType, name="platform_type"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    credentials: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Agent profile & runtime configuration
    default_chat_state: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Almaty",
        server_default="Asia/Almaty",
    )
    schedule_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: dict(DEFAULT_SCHEDULE_CONFIG),
        server_default='{"enabled": false, "timezone": "Asia/Almaty", "windows": []}',
    )
    prompt_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    llm_model_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="gpt-4o-mini",
        server_default="gpt-4o-mini",
    )
    fallback_model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rag_collection_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Cycle with Integration.bot_id: create these FKs after all tables exist
    # (bootstrap_database.py walks sorted_tables; a hard cycle skips `users`).
    ai_integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "integrations.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_bots_ai_integration_id",
        ),
        nullable=True,
    )
    crm_integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "integrations.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_bots_crm_integration_id",
        ),
        nullable=True,
    )
    low_balance_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-bot SaaS: chat requires an active subscription; settings stay editable either way.
    # New bots get an open-ended auto-trial (subscription_active=True) so they can chat immediately.
    subscription_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wallet_balance: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    llm_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    message_split: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message_buffer_delay: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    custom_code_snippet: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user: Mapped["User"] = relationship(
        back_populates="bots",
        foreign_keys=[user_id],
    )
    organization: Mapped["Company | None"] = relationship(
        "Company",
        foreign_keys=[organization_id],
        lazy="selectin",
    )
    project: Mapped["Project | None"] = relationship(
        "Project",
        back_populates="bots",
        foreign_keys=[project_id],
        lazy="selectin",
    )
    flows: Mapped[list["BotFlow"]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    clients: Mapped[list["Client"]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    knowledge_documents: Mapped[list["KnowledgeBaseDocument"]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    diagnostic_logs: Mapped[list["BotDiagnosticLog"]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    channels: Mapped[list["BotChannel"]] = relationship(
        "BotChannel",
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    builder_flows: Mapped[list["Flow"]] = relationship(
        "Flow",
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BotDiagnosticLog(Base):
    """Granular AI/runtime anomaly record for the Error Vault dashboard."""

    __tablename__ = "bot_diagnostic_logs"
    __table_args__ = (
        # ``error_type`` is the diagnostic severity/level discriminator.
        Index(
            "ix_bot_diagnostic_logs_bot_id_error_type_created_at",
            "bot_id",
            "error_type",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_type: Mapped[DiagnosticErrorType] = mapped_column(
        Enum(DiagnosticErrorType, name="diagnostic_error_type"),
        nullable=False,
        index=True,
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    bot: Mapped["Bot"] = relationship(back_populates="diagnostic_logs")
    client: Mapped["Client | None"] = relationship()


class BotFlow(Base):
    """Published or draft conversation flow graph for a bot."""

    __tablename__ = "bot_flows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Canonical graph payload: {"nodes": [...], "edges": [...], ...}
    graph_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Explicit JSONB projections (kept in sync by services; readable by SaaS APIs).
    nodes: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    edges: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    bot: Mapped["Bot"] = relationship(back_populates="flows")


class Client(Base):
    """End-user interacting with a bot (e.g. Telegram chat)."""

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("bot_id", "external_id", name="uq_clients_bot_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    first_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    current_step_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_paused_by_operator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conversation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )

    bot: Mapped["Bot"] = relationship(back_populates="clients")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    """Chat history entry for operator review and AI context."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender: Mapped[MessageSender] = mapped_column(
        Enum(MessageSender, name="message_sender"),
        nullable=False,
    )
    message_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    client: Mapped["Client"] = relationship(back_populates="messages")


class KnowledgeDocumentStatus(str, enum.Enum):
    """Lifecycle for async knowledge-base ingestion."""

    PENDING = "PENDING"
    PARSING = "PARSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class KnowledgeBaseDocument(Base):
    """Metadata record for a document indexed in the vector store for a bot."""

    __tablename__ = "knowledge_base_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="file")
    format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_context_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        Enum(
            KnowledgeDocumentStatus,
            name="knowledge_document_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=KnowledgeDocumentStatus.INDEXED,
        server_default=KnowledgeDocumentStatus.INDEXED.value,
        index=True,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default="100",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    bot: Mapped["Bot"] = relationship(back_populates="knowledge_documents")


# Domain alias used by SaaS docs / repositories.
KnowledgeBase = KnowledgeBaseDocument


class Company(Base):
    """
    Tenant Organization workspace.

    Product name: Organization. Physical table remains ``companies`` for
    backward compatibility. Subdomain / header tenancy resolves via ``slug``.
    """

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Almaty",
        server_default="Asia/Almaty",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
    # Org-level Stripe denormalized mirror (source of truth: stripe_customers).
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stripe_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
        comment="none|active|past_due|canceled|trialing|expired",
    )
    stripe_plan: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    is_suspended: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )

    memberships: Mapped[list["UserCompanyWorkspace"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# Public alias — Organization is the domain term; Company is the table.
Organization = Company


class Project(Base):
    """Project grouping bots inside an Organization (multi-tenancy tier)."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    organization: Mapped["Company"] = relationship(
        back_populates="projects",
        foreign_keys=[organization_id],
    )
    bots: Mapped[list["Bot"]] = relationship(
        back_populates="project",
        foreign_keys="Bot.project_id",
        lazy="selectin",
    )


class UserCompanyWorkspace(Base):
    """Many-to-many membership linking users to tenant organizations."""

    __tablename__ = "user_company_workspaces"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_user_company_workspace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.OWNER,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    company: Mapped["Company"] = relationship(back_populates="memberships")


class TeamInvitation(Base):
    """Pending or completed invitation for a user to join a company workspace."""

    __tablename__ = "team_invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[TeamInvitationStatus] = mapped_column(
        Enum(TeamInvitationStatus, name="team_invitation_status"),
        nullable=False,
        default=TeamInvitationStatus.PENDING,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
