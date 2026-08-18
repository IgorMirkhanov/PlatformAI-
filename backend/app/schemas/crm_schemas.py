from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

CRMPlatform = Literal["amocrm", "bitrix24"]


class AmoCRMConnectRequest(BaseModel):
    base_domain: str = Field(min_length=3, max_length=255, examples=["company.amocrm.ru"])
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=512)
    authorization_code: str = Field(min_length=1, max_length=2048)
    redirect_uri: str = Field(
        default="https://localhost/oauth",
        max_length=512,
        description="Must match the redirect URI registered in amoCRM integration settings.",
    )


class Bitrix24ConnectRequest(BaseModel):
    webhook_url: HttpUrl


class CRMPlatformStatus(BaseModel):
    platform: CRMPlatform
    connected: bool
    sync_enabled: bool = False
    label: str
    detail: str | None = None
    pipeline_id: str | None = None
    stage_id: str | None = None
    default_tags: list[str] = Field(default_factory=list)


class CRMIntegrationStatusResponse(BaseModel):
    bot_id: uuid.UUID
    platforms: list[CRMPlatformStatus]


class CRMPipelineStage(BaseModel):
    id: str
    name: str
    pipeline_id: str
    pipeline_name: str


class CRMPipelineListResponse(BaseModel):
    bot_id: uuid.UUID
    platform: CRMPlatform
    pipelines: list[CRMPipelineStage]


class CRMConnectResponse(BaseModel):
    bot_id: uuid.UUID
    platform: CRMPlatform
    connected: bool
    sync_enabled: bool = True
    message: str


class CRMIntegrationPatchRequest(BaseModel):
    sync_enabled: bool | None = None
    pipeline_id: str | None = Field(default=None, max_length=64)
    stage_id: str | None = Field(default=None, max_length=64)
    default_tags: list[str] | None = None
    base_domain: str | None = Field(default=None, max_length=255)
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=512)
    authorization_code: str | None = Field(default=None, max_length=2048)
    redirect_uri: str | None = Field(default=None, max_length=512)
    webhook_url: HttpUrl | None = None


class CRMActionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    platform: CRMPlatform = "amocrm"
    pipeline_id: str | None = None
    stage_id: str | None = Field(default=None, description="amoCRM status_id or Bitrix STAGE_ID")
    tags: list[str] = Field(default_factory=list)
    custom_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Runtime conversational attributes to attach to the CRM card.",
    )
    node_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pipeline_id", "stage_id", "node_id", mode="before")
    @classmethod
    def coerce_optional_str(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        return str(value)

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="before")
    @classmethod
    def map_status_id(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if not payload.get("stage_id") and payload.get("status_id"):
            payload["stage_id"] = payload["status_id"]
        return payload


class CRMAutomationTaskPayload(BaseModel):
    """Envelope for the Celery CRM automation worker."""

    bot_id: uuid.UUID
    session_id: uuid.UUID
    action_data: dict[str, Any] = Field(default_factory=dict)
