from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TraceNodeStep(BaseModel):
    node_id: str
    node_type: str
    label: str | None = None
    status: str = "OK"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None


class TraceTransition(BaseModel):
    """Edge traversal recorded during sandbox / live flow evaluation."""

    from_node_id: str
    to_node_id: str
    via_handle: str | None = None
    edge_id: str | None = None


class RAGChunkTrace(BaseModel):
    text: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    document_id: str | None = None
    file_name: str | None = None
    chunk_index: int | None = None


class LLMMetricsTrace(BaseModel):
    model_name: str
    system_prompt: str
    user_query: str
    raw_response: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_kzt: float = 0.0
    temperature: float = 0.5
    cache_hit: bool = False


class ExecutionTrace(BaseModel):
    nodes_triggered: list[TraceNodeStep] = Field(default_factory=list)
    transitions: list[TraceTransition] = Field(default_factory=list)
    rag_context: list[RAGChunkTrace] = Field(default_factory=list)
    llm_metrics: LLMMetricsTrace | None = None
    errors: list[str] = Field(default_factory=list)
    simulation: bool = True
    current_node_id: str | None = None


class SandboxMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class SandboxChatResponse(BaseModel):
    message: str
    trace: ExecutionTrace
    session_id: str
    current_step_id: str | None = None
    # Visual tracing / billing fields expected by Live Sandbox UI.
    node_execution_trace: list[TraceNodeStep] = Field(default_factory=list)
    execution_context: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    credits_charged: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class SandboxClearResponse(BaseModel):
    bot_id: uuid.UUID
    session_id: str
    cleared: bool = True
    message: str = "Sandbox session cleared."


class SandboxWsInbound(BaseModel):
    type: str = Field(default="message")
    text: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class SandboxWsOutbound(BaseModel):
    type: str = "response"
    message: str
    trace: ExecutionTrace
    session_id: str
    current_step_id: str | None = None
    error: str | None = None
    node_execution_trace: list[TraceNodeStep] = Field(default_factory=list)
    execution_context: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    credits_charged: int = 0
