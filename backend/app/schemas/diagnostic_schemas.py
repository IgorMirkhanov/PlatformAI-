import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.core_models import DiagnosticErrorType


class DiagnosticLogRead(BaseModel):
    """Safe read model for AI Error Vault dashboard rows."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    bot_name: str = ""
    client_id: uuid.UUID | None = None
    error_type: DiagnosticErrorType
    error_message: str
    node_id: str | None = None
    created_at: datetime


class DiagnosticLogListResponse(BaseModel):
    logs: list[DiagnosticLogRead] = Field(default_factory=list)
    total: int = 0


class DiagnosticsExportResponse(BaseModel):
    """Markdown dump optimized for Cursor Composer / LLM debugging."""

    markdown: str
    bot_id: uuid.UUID | None = None
    bot_name: str | None = None
    error_count: int = 0
    generated_at: datetime
