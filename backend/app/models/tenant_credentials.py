"""BYOK tenant credential vault — AES-256-GCM payloads (architecture spec §1.2)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CredentialKind(str, enum.Enum):
    LLM_OPENAI = "llm_openai"
    LLM_DEEPSEEK = "llm_deepseek"
    LLM_ANTHROPIC = "llm_anthropic"
    LLM_GROQ = "llm_groq"
    LLM_OPENROUTER = "llm_openrouter"
    LLM_GEMINI = "llm_gemini"
    CHANNEL_TELEGRAM = "channel_telegram"
    CHANNEL_WAZZUP = "channel_wazzup"
    CHANNEL_GREENAPI = "channel_greenapi"
    CHANNEL_WIDGET = "channel_widget"
    CRM_AMOCRM = "crm_amocrm"
    CRM_BITRIX24 = "crm_bitrix24"
    KASPI_PAY = "kaspi_pay"


class CredentialStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


LLM_KIND_TO_PROVIDER: dict[str, str] = {
    CredentialKind.LLM_OPENAI.value: "openai",
    CredentialKind.LLM_DEEPSEEK.value: "deepseek",
    CredentialKind.LLM_ANTHROPIC.value: "anthropic",
    CredentialKind.LLM_GROQ.value: "groq",
    CredentialKind.LLM_OPENROUTER.value: "openrouter",
    CredentialKind.LLM_GEMINI.value: "gemini",
}

PROVIDER_TO_LLM_KIND: dict[str, str] = {v: k for k, v in LLM_KIND_TO_PROVIDER.items()}


class TenantCredential(Base):
    """Universal encrypted secret store (LLM / messenger / CRM)."""

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("organization_id", "kind", "label", name="uq_credentials_org_kind_label"),
        Index(
            "idx_credentials_oauth_refresh",
            "oauth_expires_at",
            postgresql_where=text(
                "kind IN ('crm_amocrm', 'crm_bitrix24') AND status = 'active'"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_iv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_tag: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    oauth_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    oauth_refresh_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CredentialStatus.ACTIVE.value, server_default="active"
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WebhookEventLog(Base):
    """Durable inbound idempotency backstop (Redis lock is the fast path)."""

    __tablename__ = "webhook_event_log"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "reference_id",
            "external_message_id",
            name="uq_webhook_event_log_provider_ref_msg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unmatched: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
