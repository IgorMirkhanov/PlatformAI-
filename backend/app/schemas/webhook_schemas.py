"""Strict Pydantic models for Telegram Bot API and WhatsApp Cloud API webhooks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | str
    is_bot: bool | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | str
    type: str | None = None
    title: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: int | None = None
    date: int | None = None
    chat: TelegramChat
    from_user: TelegramUser | None = Field(default=None, alias="from")
    text: str | None = None
    caption: str | None = None


class TelegramCallbackQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    from_user: TelegramUser | None = Field(default=None, alias="from")
    message: TelegramMessage | None = None
    data: str | None = None
    chat_instance: str | None = None


class TelegramUpdate(BaseModel):
    """Incoming Telegram Bot API update envelope."""

    model_config = ConfigDict(extra="ignore")

    update_id: int | None = None
    message: TelegramMessage | None = None
    edited_message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None

    def to_raw_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class ParsedTelegramInbound(BaseModel):
    """Normalized fields extracted from a Telegram update for flow execution."""

    chat_id: str = Field(min_length=1)
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    message_text: str = ""
    content_type: str = "text"
    callback_query_id: str | None = None


class WhatsAppTextBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    body: str = ""


class WhatsAppMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_: str = Field(default="", alias="from")
    id: str | None = None
    timestamp: str | None = None
    type: str = "text"
    text: WhatsAppTextBody | None = None

    @field_validator("from_", mode="before")
    @classmethod
    def coerce_from(cls, value: Any) -> str:
        return str(value or "")


class WhatsAppContactProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None


class WhatsAppContact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: WhatsAppContactProfile | None = None
    wa_id: str | None = None


class WhatsAppValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messaging_product: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    contacts: list[WhatsAppContact] = Field(default_factory=list)
    messages: list[WhatsAppMessage] = Field(default_factory=list)


class WhatsAppChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str | None = None
    value: WhatsAppValue = Field(default_factory=WhatsAppValue)


class WhatsAppEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    changes: list[WhatsAppChange] = Field(default_factory=list)


class WhatsAppWebhookPayload(BaseModel):
    """Meta WhatsApp Cloud API webhook body."""

    model_config = ConfigDict(extra="ignore")

    object: Literal["whatsapp_business_account"] | str | None = None
    entry: list[WhatsAppEntry] = Field(default_factory=list)

    def to_raw_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class ParsedWhatsAppInbound(BaseModel):
    external_id: str = Field(min_length=1, description="Sender phone / wa_id")
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    message_text: str = ""
    content_type: str = "text"
