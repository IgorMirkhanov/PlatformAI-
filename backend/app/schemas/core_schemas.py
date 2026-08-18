import enum
import secrets
import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.core_models import (
    BillingTransactionStatus,
    BillingTransactionType,
    MessageSender,
    PlatformType,
    SubscriptionPlanName,
    SubscriptionStatus,
)
from app.schemas.graph_validation import GraphValidationError, GraphValidationIssue
from app.schemas.media_schemas import MediaAttachment


# ---------------------------------------------------------------------------
# Flow graph schemas (React Flow compatible)
# ---------------------------------------------------------------------------


class FlowButton(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)


class TriggerNodeData(BaseModel):
    trigger_type: Literal["message_received", "webhook", "manual"] = "message_received"
    webhook_event: str = ""


class TextMessageNodeData(BaseModel):
    text: str = Field(min_length=1)
    buttons: list[FlowButton] = Field(default_factory=list)


class AIAgentNodeData(BaseModel):
    prompt_context: str = Field(min_length=1)
    knowledge_base_id: str = Field(min_length=1)
    prompt_modifier: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    variables: list[str] = Field(default_factory=list)


class ConditionNodeData(BaseModel):
    condition_type: Literal["customer_tag", "working_hours", "expression"] = "customer_tag"
    tag: str = ""
    expression: str = "true"
    true_label: str | None = "Match"
    false_label: str | None = "Else"


class ApiRequestNodeData(BaseModel):
    method: Literal["GET", "POST"] = "POST"
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str = ""
    variable_name: str = "api_response"
    success_label: str | None = "Success"
    failure_label: str | None = "Failure"


class KnowledgeSearchNodeData(BaseModel):
    """RAG intermediary: Chroma similarity search → session variables for LLM templates."""

    top_k: int = Field(default=3, ge=1, le=10)
    query_variable: str = "message"
    output_variable: str = "rag_context"
    knowledge_base_id: str = ""


class CRMActionNodeData(BaseModel):
    """CRM Action / Custom Webhook node (Phase A HTTP integration)."""

    action_type: str = Field(default="custom_webhook", min_length=1)
    integration_type: Literal["custom_webhook", "amocrm", "bitrix24"] = "custom_webhook"
    method: Literal["GET", "POST", "PUT"] = "POST"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str = ""
    response_variable: str = "crm_result"
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_integration_aliases(self) -> Self:
        # Prefer explicit integration_type; keep action_type aligned for older graphs.
        if self.integration_type:
            self.action_type = self.integration_type
        elif self.action_type in {"custom_webhook", "amocrm", "bitrix24"}:
            self.integration_type = self.action_type  # type: ignore[assignment]
        if not self.response_variable.strip():
            self.response_variable = "crm_result"
        return self


FlowNodeType = Literal[
    "trigger",
    "text_message",
    "condition",
    "ai_agent",
    "knowledge_search",
    "crm_action",
    "api_request",
]

NODE_DATA_VALIDATORS: dict[FlowNodeType, type[BaseModel]] = {
    "trigger": TriggerNodeData,
    "text_message": TextMessageNodeData,
    "condition": ConditionNodeData,
    "ai_agent": AIAgentNodeData,
    "knowledge_search": KnowledgeSearchNodeData,
    "crm_action": CRMActionNodeData,
    "api_request": ApiRequestNodeData,
}


class FlowNode(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    type: FlowNodeType
    data: dict[str, Any]
    position: dict[str, float] | None = None

    @model_validator(mode="after")
    def validate_data_for_type(self) -> Self:
        validator = NODE_DATA_VALIDATORS[self.type]
        validated = validator.model_validate(self.data)
        # Persist a fully-normalized payload so nested Condition / API configs
        # round-trip identically through PostgreSQL JSONB and the executor.
        self.data = validated.model_dump(mode="json")
        return self


class FlowEdge(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    sourceHandle: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(populate_by_name=True)


class FlowGraphData(BaseModel):
    """Strict validation for React Flow graph payloads stored in bot_flows.graph_data."""

    nodes: list[FlowNode] = Field(min_length=1)
    edges: list[FlowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> Self:
        issues: list[GraphValidationIssue] = []
        node_ids = {node.id for node in self.nodes}

        for edge in self.edges:
            if edge.source not in node_ids:
                issues.append(
                    GraphValidationIssue(
                        code="edge_unknown_source",
                        message=(
                            f"Edge '{edge.id}' connects from unknown node '{edge.source}'. "
                            "Link the edge to an existing canvas node."
                        ),
                        edge_id=edge.id,
                        node_id=edge.source,
                        field="edges",
                    )
                )
            if edge.target not in node_ids:
                issues.append(
                    GraphValidationIssue(
                        code="edge_unknown_target",
                        message=(
                            f"Edge '{edge.id}' points to unknown node '{edge.target}'. "
                            "Connect the edge to a valid target node."
                        ),
                        edge_id=edge.id,
                        node_id=edge.target,
                        field="edges",
                    )
                )

        if self.nodes:
            incoming_targets = {edge.target for edge in self.edges}
            start_candidates = [node for node in self.nodes if node.id not in incoming_targets]
            if not start_candidates:
                issues.append(
                    GraphValidationIssue(
                        code="graph_no_start_node",
                        message=(
                            "Graph has no entry node. Add a node without incoming edges "
                            "(typically your welcome / text message step)."
                        ),
                        field="nodes",
                    )
                )

        for node in self.nodes:
            if node.type != "text_message":
                continue

            buttons = node.data.get("buttons", [])
            button_ids = {btn["id"] for btn in buttons}

            for edge in self.edges:
                if edge.source != node.id or edge.sourceHandle is None:
                    continue
                if edge.sourceHandle not in button_ids:
                    issues.append(
                        GraphValidationIssue(
                            code="edge_unknown_button_handle",
                            message=(
                                f"Edge '{edge.id}' uses button handle '{edge.sourceHandle}' "
                                f"but node '{node.id}' has no matching button id."
                            ),
                            edge_id=edge.id,
                            node_id=node.id,
                            button_id=edge.sourceHandle,
                            field="edges",
                        )
                    )

            for button in buttons:
                button_id = button["id"]
                has_edge = any(
                    edge.source == node.id and edge.sourceHandle == button_id
                    for edge in self.edges
                )
                if buttons and not has_edge:
                    issues.append(
                        GraphValidationIssue(
                            code="button_without_target",
                            message=(
                                f"Button '{button.get('text', button_id)}' on node '{node.id}' "
                                "is not connected to any target node."
                            ),
                            node_id=node.id,
                            button_id=button_id,
                            field="buttons",
                        )
                    )

        for node in self.nodes:
            if node.type == "condition":
                for handle in ("true", "false"):
                    has_edge = any(
                        edge.source == node.id and edge.sourceHandle == handle
                        for edge in self.edges
                    )
                    if not has_edge:
                        issues.append(
                            GraphValidationIssue(
                                code="condition_branch_unconnected",
                                message=(
                                    f"Condition node '{node.id}' must connect both "
                                    f"'{handle}' branches to downstream nodes."
                                ),
                                node_id=node.id,
                                button_id=handle,
                                field="edges",
                            )
                        )

            if node.type == "api_request":
                for handle in ("success", "failure"):
                    has_edge = any(
                        edge.source == node.id and edge.sourceHandle == handle
                        for edge in self.edges
                    )
                    if not has_edge:
                        issues.append(
                            GraphValidationIssue(
                                code="api_request_outcome_unconnected",
                                message=(
                                    f"API Request node '{node.id}' must connect both "
                                    f"'{handle}' outcome handles."
                                ),
                                node_id=node.id,
                                button_id=handle,
                                field="edges",
                            )
                        )

        if issues:
            raise GraphValidationError(issues)

        return self


# ---------------------------------------------------------------------------
# Bot schemas
# ---------------------------------------------------------------------------


class BotBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    platform_type: PlatformType
    is_active: bool = True
    credentials: dict[str, Any] = Field(default_factory=dict)


class BotCreate(BotBase):
    user_id: uuid.UUID


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    platform_type: PlatformType | None = None
    is_active: bool | None = None
    credentials: dict[str, Any] | None = None


class BotRead(BotBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID


# ---------------------------------------------------------------------------
# BotFlow schemas
# ---------------------------------------------------------------------------


class BotFlowBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    graph_data: FlowGraphData
    is_published: bool = False


class BotFlowCreate(BotFlowBase):
    bot_id: uuid.UUID


class BotFlowUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    graph_data: FlowGraphData | None = None
    is_published: bool | None = None


class BotFlowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    title: str
    graph_data: FlowGraphData
    is_published: bool
    updated_at: datetime

    @field_validator("graph_data", mode="before")
    @classmethod
    def validate_graph_data(cls, value: Any) -> Any:
        if isinstance(value, FlowGraphData):
            return value
        if isinstance(value, dict):
            return FlowGraphData.model_validate(value)
        return value


class BotFlowResponse(BaseModel):
    """Flow graph payload for canvas restoration (published, draft, or default template)."""

    bot_id: uuid.UUID
    flow_id: uuid.UUID | None = None
    title: str
    graph_data: dict[str, Any]
    is_published: bool
    is_default_template: bool = False
    updated_at: datetime | None = None

    @field_validator("graph_data", mode="before")
    @classmethod
    def coerce_loose_graph(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, FlowGraphData):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {
                "nodes": value.get("nodes") or [],
                "edges": value.get("edges") or [],
            }
        return {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Client schemas
# ---------------------------------------------------------------------------


class ClientBase(BaseModel):
    external_id: str = Field(min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    first_name: str = Field(default="", max_length=255)
    current_step_id: str = Field(default="", max_length=255)
    is_paused_by_operator: bool = False


class ClientCreate(ClientBase):
    bot_id: uuid.UUID


class ClientUpdate(BaseModel):
    username: str | None = Field(default=None, max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    current_step_id: str | None = Field(default=None, max_length=255)
    is_paused_by_operator: bool | None = None


class ClientRead(ClientBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID


# ---------------------------------------------------------------------------
# ChatMessage schemas
# ---------------------------------------------------------------------------


class ChatMessageBase(BaseModel):
    sender: MessageSender
    message_text: str = Field(default="", max_length=10000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatMessageCreate(ChatMessageBase):
    client_id: uuid.UUID


class ChatMessageUpdate(BaseModel):
    message_text: str | None = Field(default=None, max_length=10000)
    payload: dict[str, Any] | None = None


class ChatMessageRead(ChatMessageBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Webhook simulator schemas
# ---------------------------------------------------------------------------


class WebhookSimulateRequest(BaseModel):
    bot_id: uuid.UUID
    external_id: str = Field(min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    message_text: str = Field(default="", max_length=10000)


class WebhookQueuedResponse(BaseModel):
    status: Literal["queued"] = "queued"
    task_id: str | None = None


class WebhookSimulateResponse(BaseModel):
    response_text: str
    buttons: list[FlowButton] = Field(default_factory=list)
    current_step_id: str
    node_type: str | None = None
    is_waiting: bool = False
    is_terminal: bool = False
    bot_silent: bool = False
    client_id: uuid.UUID | None = None
    media_attachments: list[MediaAttachment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Bot management & Telegram integration schemas
# ---------------------------------------------------------------------------


class PublishBotFlowRequest(BaseModel):
    """Canvas publish payload — graph_data nodes carry typed nested configs."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="Published Flow", min_length=1, max_length=255)
    graph_data: FlowGraphData
    is_published: bool = True

    @field_validator("graph_data", mode="before")
    @classmethod
    def coerce_graph_data(cls, value: Any) -> Any:
        """Accept raw JSON or already-parsed FlowGraphData from the canvas."""
        if isinstance(value, FlowGraphData):
            return value
        if isinstance(value, dict):
            return FlowGraphData.model_validate(value)
        raise TypeError("graph_data must be an object with nodes and edges")

    def compiled_graph_dump(self) -> dict[str, Any]:
        """Serialize validated nodes (incl. Condition / API nested data) for JSONB."""
        return self.graph_data.model_dump(mode="json")


class SaveBotFlowRequest(BaseModel):
    """
    Persist a draft canvas graph without full publish-time branch integrity checks.

    Accepts either top-level ``nodes``/``edges`` or nested ``graph_data``.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="Saved Flow", min_length=1, max_length=255)
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    graph_data: dict[str, Any] | None = None
    is_published: bool = False

    def resolve_graph_payload(self) -> dict[str, Any]:
        if self.graph_data and isinstance(self.graph_data, dict):
            nodes = self.graph_data.get("nodes") or []
            edges = self.graph_data.get("edges") or []
        else:
            nodes = self.nodes or []
            edges = self.edges or []
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("nodes and edges must be arrays")

        normalized_nodes: list[dict[str, Any]] = []
        for raw in nodes:
            if not isinstance(raw, dict):
                continue
            try:
                node = FlowNode.model_validate(raw)
                dump = node.model_dump(mode="json")
                if raw.get("position") is not None:
                    dump["position"] = raw.get("position")
                normalized_nodes.append(dump)
            except ValidationError:
                # Keep raw node so drafts are never blocked mid-edit.
                normalized_nodes.append(raw)

        normalized_edges: list[dict[str, Any]] = []
        for raw in edges:
            if not isinstance(raw, dict):
                continue
            try:
                edge = FlowEdge.model_validate(raw)
                normalized_edges.append(edge.model_dump(mode="json", by_alias=True))
            except ValidationError:
                normalized_edges.append(raw)

        return {"nodes": normalized_nodes, "edges": normalized_edges}


class PublishBotFlowResponse(BaseModel):
    bot_id: uuid.UUID
    flow_id: uuid.UUID
    title: str
    is_published: bool
    node_count: int
    edge_count: int
    message: str = "Flow published successfully."


class TelegramSetupRequest(BaseModel):
    bot_token: str = Field(min_length=20, max_length=256)
    bot_name: str = Field(default="Telegram Bot", min_length=1, max_length=255)
    user_id: uuid.UUID | None = None


class TelegramSetupResponse(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    token_hash: str
    webhook_url: str
    telegram_username: str | None = None
    message: str = "Telegram bot connected and webhook registered."


class AgentUseCaseTemplate(str, enum.Enum):
    SUPPORT_RAG = "support_rag"
    SALES_CRM = "sales_crm"
    EMPTY = "empty"


class CreateBotRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    platform_type: PlatformType = PlatformType.TELEGRAM
    user_id: uuid.UUID | None = None
    use_case: AgentUseCaseTemplate = AgentUseCaseTemplate.EMPTY


class CreateBotResponse(BaseModel):
    bot_id: uuid.UUID
    name: str
    platform_type: PlatformType
    is_active: bool
    message: str = "Bot instance created successfully."


class ChannelIntegrationType(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    VKONTAKTE = "vkontakte"
    WEB_WIDGET = "web_widget"


class SetupChannelRequest(BaseModel):
    channel_type: ChannelIntegrationType | None = None
    telegram_bot_token: str | None = Field(default=None, min_length=20, max_length=256)
    telegram_active: bool | None = None
    whatsapp_phone_number_id: str | None = Field(default=None, min_length=1, max_length=128)
    whatsapp_business_account_id: str | None = Field(default=None, min_length=1, max_length=128)
    whatsapp_access_token: str | None = Field(default=None, min_length=10, max_length=512)
    whatsapp_verify_token: str | None = Field(default=None, min_length=1, max_length=128)
    instagram_page_id: str | None = Field(default=None, min_length=1, max_length=128)
    instagram_access_token: str | None = Field(default=None, min_length=10, max_length=512)
    vk_group_id: str | None = Field(default=None, min_length=1, max_length=128)
    vk_access_token: str | None = Field(default=None, min_length=10, max_length=512)
    web_widget_active: bool | None = None

    @model_validator(mode="after")
    def validate_channel_payload(self) -> Self:
        channel = self.channel_type
        if channel is None:
            return self

        if channel == ChannelIntegrationType.TELEGRAM and not self.telegram_bot_token:
            raise ValueError("telegram_bot_token is required for Telegram channel setup.")
        if channel == ChannelIntegrationType.WHATSAPP:
            if not self.whatsapp_phone_number_id or not self.whatsapp_access_token:
                raise ValueError(
                    "whatsapp_phone_number_id and whatsapp_access_token are required for WhatsApp."
                )
            if not self.whatsapp_business_account_id:
                raise ValueError("whatsapp_business_account_id is required for WhatsApp Business API.")
        if channel == ChannelIntegrationType.INSTAGRAM:
            if not self.instagram_page_id or not self.instagram_access_token:
                raise ValueError(
                    "instagram_page_id and instagram_access_token are required for Instagram Direct."
                )
        if channel == ChannelIntegrationType.VKONTAKTE:
            if not self.vk_group_id or not self.vk_access_token:
                raise ValueError("vk_group_id and vk_access_token are required for VKontakte.")
        return self


class SetupChannelResponse(BaseModel):
    bot_id: uuid.UUID
    platform_type: PlatformType
    channel_type: ChannelIntegrationType | None = None
    channel_connected: bool
    channel_active: bool = True
    webhook_url: str | None = None
    token_hash: str | None = None
    telegram_username: str | None = None
    verify_token: str | None = None
    embed_script: str | None = None
    message: str


class ChannelStatusItem(BaseModel):
    channel_type: ChannelIntegrationType
    connected: bool
    active: bool
    webhook_url: str | None = None
    verify_token: str | None = None
    embed_script: str | None = None
    telegram_username: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class BotChannelsResponse(BaseModel):
    bot_id: uuid.UUID
    channels: list[ChannelStatusItem]


def generate_whatsapp_verify_token() -> str:
    return secrets.token_urlsafe(24)


class BotHealthTelemetry(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    platform_type: PlatformType
    is_active: bool
    channel_connected: bool
    flow_published: bool
    validation_status: str
    node_count: int
    edge_count: int
    flow_updated_at: datetime | None = None
    webhook_url: str | None = None
    issues: list[GraphValidationIssue] = Field(default_factory=list)


class BotHealthListResponse(BaseModel):
    bots: list[BotHealthTelemetry]
    total: int


# ---------------------------------------------------------------------------
# Operator inbox / live chat schemas
# ---------------------------------------------------------------------------


class ActiveChatSummary(BaseModel):
    client_id: uuid.UUID
    bot_id: uuid.UUID
    bot_name: str
    platform_type: PlatformType
    external_id: str
    username: str
    first_name: str
    phone: str | None = None
    tags: list[str] = Field(default_factory=list)
    current_step_id: str
    state_label: str
    is_paused_by_operator: bool
    is_closed: bool = False
    last_message_text: str
    last_message_sender: MessageSender | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0


class ActiveChatsResponse(BaseModel):
    chats: list[ActiveChatSummary]
    total: int


class ManualMessageRequest(BaseModel):
    message_text: str = Field(min_length=1, max_length=10000)


class ToggleOperatorRequest(BaseModel):
    paused: bool | None = None


class ToggleOperatorResponse(BaseModel):
    client_id: uuid.UUID
    is_paused_by_operator: bool
    state_label: str
    message: str


class InterceptChatRequest(BaseModel):
    action: Literal["intercept", "release"] | None = None


class InterceptChatResponse(BaseModel):
    session_id: uuid.UUID
    client_id: uuid.UUID
    is_paused_by_operator: bool
    state_label: str
    routing_mode: Literal["operator", "bot"]
    message: str


class CrmPlatformLinkage(BaseModel):
    connected: bool = False
    sync_enabled: bool = False
    lead_id: str | None = None
    deal_id: str | None = None
    stage_label: str | None = None
    pipeline_label: str | None = None


class CrmLinkageCard(BaseModel):
    amocrm: CrmPlatformLinkage | None = None
    bitrix24: CrmPlatformLinkage | None = None


class ClientInboxProfile(BaseModel):
    client_id: uuid.UUID
    bot_id: uuid.UUID
    bot_name: str
    platform_type: PlatformType
    display_name: str
    phone: str | None = None
    username: str
    external_id: str
    tags: list[str] = Field(default_factory=list)
    is_paused_by_operator: bool
    state_label: str
    is_closed: bool = False
    crm: CrmLinkageCard = Field(default_factory=CrmLinkageCard)


class CreateCrmDealResponse(BaseModel):
    success: bool
    platform: str | None = None
    lead_id: str | None = None
    deal_id: str | None = None
    message: str


# ---------------------------------------------------------------------------
# Agent profile / advanced bot configuration schemas
# ---------------------------------------------------------------------------


class ScheduleWindow(BaseModel):
    day: str = Field(min_length=2, max_length=16)
    start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    end: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")


class ScheduleConfig(BaseModel):
    enabled: bool = False
    timezone: str = Field(default="Asia/Almaty", max_length=64)
    windows: list[ScheduleWindow] = Field(default_factory=list)
    day_enabled: dict[str, bool] | None = None


class BotSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    default_chat_state: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    schedule_config: ScheduleConfig | None = None
    message_split: bool | None = None
    message_buffer_delay: int | None = Field(default=None, ge=0, le=60000)


class BotPromptingUpdate(BaseModel):
    prompt_instructions: str | None = Field(default=None, max_length=50000)
    llm_model_name: str | None = Field(default=None, min_length=1, max_length=128)
    llm_temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    show_username_visibility: bool | None = None
    show_messenger_visibility: bool | None = None
    show_datetime_visibility: bool | None = None


class EnhancePromptRequest(BaseModel):
    prompt_instructions: str = Field(min_length=1, max_length=50000)


class EnhancePromptResponse(BaseModel):
    bot_id: uuid.UUID
    enhanced_prompt: str
    message: str = "Prompt enhanced successfully."


class OptimizePromptRequest(BaseModel):
    prompt_instructions: str = Field(min_length=1, max_length=50000)


class OptimizePromptResponse(BaseModel):
    bot_id: uuid.UUID
    optimized_prompt: str
    message: str = "Prompt optimized successfully."


class OptimizeAIPromptRequest(BaseModel):
    """Flow builder / generic prompt optimization (org-billed)."""

    prompt_text: str = Field(min_length=1, max_length=50000)
    bot_task: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional bot use-case or task description for better structuring.",
    )


class OptimizeAIPromptResponse(BaseModel):
    optimized_prompt: str
    model_name: str = "gpt-4o-mini"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    message: str = "Prompt optimized successfully."


class BotLLMConfigUpdate(BaseModel):
    llm_model_name: str = Field(default="gpt-4o-mini", min_length=1, max_length=128)
    llm_temperature: float = Field(default=0.5, ge=0.0, le=2.0)


class BotFunctionsUpdate(BaseModel):
    custom_code_snippet: str | None = Field(default=None, max_length=100000)
    function_tools: list[dict[str, Any]] | None = None


class BotAvatarUploadResponse(BaseModel):
    bot_id: uuid.UUID
    avatar_url: str
    message: str = "Avatar uploaded successfully."


class BotAgentProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    platform_type: PlatformType
    is_active: bool
    default_chat_state: bool
    timezone: str
    schedule_config: dict[str, Any]
    prompt_instructions: str
    llm_model_name: str
    llm_temperature: float
    message_split: bool
    message_buffer_delay: int
    custom_code_snippet: str
    function_tools: list[dict[str, Any]] = Field(default_factory=list)
    agent_rag: list[dict[str, Any]] = Field(default_factory=list)
    openai_tools: list[dict[str, Any]] = Field(default_factory=list)
    show_username_visibility: bool = False
    show_messenger_visibility: bool = False
    show_datetime_visibility: bool = False
    avatar_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def inject_avatar_url(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        from app.services.bot_workspace_config import get_workspace, openai_tools_for_bot

        credentials = getattr(data, "credentials", None) or {}
        if not isinstance(credentials, dict):
            credentials = {}
        workspace = get_workspace(data)
        payload = {
            field: getattr(data, field)
            for field in (
                "id",
                "user_id",
                "name",
                "platform_type",
                "is_active",
                "default_chat_state",
                "timezone",
                "schedule_config",
                "prompt_instructions",
                "llm_model_name",
                "llm_temperature",
                "message_split",
                "message_buffer_delay",
                "custom_code_snippet",
            )
        }
        payload["avatar_url"] = (
            str(credentials["avatar_url"]) if credentials.get("avatar_url") else None
        )
        payload["function_tools"] = workspace["functions"]
        payload["agent_rag"] = workspace["agent_rag"]
        payload["openai_tools"] = openai_tools_for_bot(data)
        return payload

    @model_validator(mode="after")
    def inject_prompting_visibility(self) -> Self:
        visibility = (self.schedule_config or {}).get("prompting_visibility") or {}
        return self.model_copy(
            update={
                "show_username_visibility": bool(
                    visibility.get("show_username_visibility", False),
                ),
                "show_messenger_visibility": bool(
                    visibility.get("show_messenger_visibility", False),
                ),
                "show_datetime_visibility": bool(
                    visibility.get("show_datetime_visibility", False),
                ),
            },
        )


# ---------------------------------------------------------------------------
# Subscription & billing schemas
# ---------------------------------------------------------------------------


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    plan_name: SubscriptionPlanName
    balance: float
    status: SubscriptionStatus
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SubscriptionCreate(BaseModel):
    user_id: uuid.UUID | None = None
    plan_name: SubscriptionPlanName = SubscriptionPlanName.FREE
    balance: float = Field(default=0.0, ge=0)
    expires_at: datetime | None = None


class BalanceTopUpRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    user_id: uuid.UUID | None = None


class SubscribeRequest(BaseModel):
    plan_name: SubscriptionPlanName
    user_id: uuid.UUID | None = None
    mock_payment_reference: str | None = Field(default=None, max_length=128)


class BillingStatusResponse(BaseModel):
    user_id: uuid.UUID
    plan_name: SubscriptionPlanName
    balance: float
    bonus_balance: float = 0.0
    currency: str = "KZT"
    status: SubscriptionStatus
    expires_at: datetime | None = None
    days_remaining: int | None = None
    active_agents_limit: int = 1
    is_low_balance: bool = False
    low_balance_threshold_kzt: float = 2500.0
    message: str = "Billing status loaded."


class BillingTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    transaction_type: BillingTransactionType
    amount: float
    currency: str
    description: str
    receipt_url: str | None = None
    status: BillingTransactionStatus
    reference_id: str | None = None
    created_at: datetime


class BillingTransactionListResponse(BaseModel):
    transactions: list[BillingTransactionRead]
    total: int


class DepositRequestResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    amount: float
    currency: str = "KZT"
    receipt_url: str
    status: BillingTransactionStatus
    message: str
    created_at: datetime


class SystemNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    category: str
    severity: str
    title: str
    message: str
    reference_id: str | None = None
    is_read: bool
    created_at: datetime


class SystemNotificationListResponse(BaseModel):
    notifications: list[SystemNotificationRead]
    total: int
    unread_critical: int = 0


class SubscribeResponse(BaseModel):
    subscription: SubscriptionRead
    message: str


# ---------------------------------------------------------------------------
# Dashboard analytics schemas
# ---------------------------------------------------------------------------


class AgentStatusSummary(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    platform_type: PlatformType
    is_active: bool
    channel_connected: bool
    flow_published: bool
    unique_dialogs: int
    connected_channels: list[str] = Field(default_factory=list)


class DashboardStatsResponse(BaseModel):
    total_unique_dialogs: int
    total_messages_dispatched: int
    api_token_expenditure: float
    active_agents: int
    inactive_agents: int
    subscription_balance: float
    subscription_plan: SubscriptionPlanName
    agents: list[AgentStatusSummary]
    period_label: str = "all_time"


# ---------------------------------------------------------------------------
# Knowledge base schemas (re-exported for API consistency)
# ---------------------------------------------------------------------------

from app.schemas.knowledge_base_schemas import (  # noqa: E402
    KnowledgeBaseDeleteResponse,
    KnowledgeBaseDocumentItem,
    KnowledgeBaseDocumentListResponse,
    KnowledgeBaseUploadRequest,
    KnowledgeBaseUploadResponse,
)

