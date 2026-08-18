import type { Edge, Node } from "reactflow";

import type {
  CRMActionExportData,
  CRMActionNodeData,
  CRMIntegrationType,
} from "@/types/crm";
import { recordToHeaders } from "@/types/crm";

/** Backend-compatible node types from flow_graph_spec.md */
export type BackendNodeType =
  | "trigger"
  | "text_message"
  | "condition"
  | "ai_agent"
  | "knowledge_search"
  | "crm_action"
  | "api_request"
  | "loop"
  | "human_handoff"
  | "google_sheets"
  | "sql_query"
  | "image_generation";

/**
 * Canonical NodeType enum (product vocabulary).
 * Maps 1:1 onto canvas identifiers where possible.
 */
export enum NodeType {
  Trigger = "trigger",
  TextMessage = "textMessage",
  WhatsApp = "whatsapp",
  Condition = "condition",
  LLM = "llm",
  RAG = "rag",
  APICall = "apiRequest",
  CRMAction = "crmAction",
  Loop = "loop",
  HumanHandoff = "humanHandoff",
  GoogleSheets = "googleSheets",
  SqlQuery = "sqlQuery",
  ImageGeneration = "imageGeneration",
}

/** React Flow canvas node type identifiers */
export type CanvasNodeType =
  | "trigger"
  | "textMessage"
  | "condition"
  | "aiAgent"
  | "llm"
  | "knowledgeSearch"
  | "rag"
  | "crmAction"
  | "crm"
  | "apiRequest"
  | "whatsapp"
  | "loop"
  | "humanHandoff"
  | "googleSheets"
  | "sqlQuery"
  | "imageGeneration";

export type ConditionType = "customer_tag" | "working_hours" | "expression";

export type TriggerType = "message_received" | "webhook" | "manual";

export type ApiHttpMethod = "GET" | "POST";

export interface FlowButton {
  id: string;
  text: string;
}

export interface TriggerNodeData {
  label: string;
  trigger_type: TriggerType;
  webhook_event: string;
}

export interface TextMessageNodeData {
  label: string;
  text: string;
  buttons: FlowButton[];
}

/** WhatsApp-oriented outbound (serializes to text_message + channel metadata). */
export interface WhatsAppNodeData {
  label: string;
  text: string;
  buttons: FlowButton[];
  media_url?: string;
  channel: "whatsapp";
}

export interface AIAgentNodeData {
  label: string;
  prompt_context: string;
  knowledge_base_id: string;
  prompt_modifier: string;
  temperature?: number;
  model_name?: string;
  variables?: string[];
}

/** Alias for the LLM canvas node (same payload as AI Agent). */
export type LLMNodeData = AIAgentNodeData;

export interface ConditionNodeData {
  label: string;
  condition_type: ConditionType;
  tag: string;
  expression: string;
  true_label: string;
  false_label: string;
}

export interface ApiRequestNodeData {
  label: string;
  method: ApiHttpMethod;
  url: string;
  headers: Record<string, string>;
  body_template: string;
  variable_name: string;
  success_label: string;
  failure_label: string;
}

/** RAG intermediary — similarity search → session variable for LLM templates. */
export interface KnowledgeSearchNodeData {
  label: string;
  top_k: number;
  query_variable: string;
  output_variable: string;
  knowledge_base_id: string;
}

/** Product alias for Knowledge Search. */
export type RAGNodeData = KnowledgeSearchNodeData;

/** Product alias for API Request. */
export type APICallNodeData = ApiRequestNodeData;

export interface LoopNodeData {
  label: string;
  /** Max iterations before forcing the exit handle. */
  max_iterations: number;
  /** Expression / variable that keeps the loop alive when truthy. */
  continue_expression: string;
  body_label: string;
  exit_label: string;
}

export interface HumanHandoffNodeData {
  label: string;
  /** Message shown to the end-user when pausing for an operator. */
  handoff_message: string;
  /** Optional inbox / queue tag for routing. */
  queue_tag: string;
  pause_bot: boolean;
}

export type GoogleSheetsAction = "append_row" | "read_row";

/** One column↔variable mapping entry. */
export interface GoogleSheetsColumnMapping {
  /** Sheet column key / header (e.g. "A", "email", "Name"). */
  column_key: string;
  /** Session variable name (e.g. "user_email"). */
  variable_name: string;
}

export interface GoogleSheetsNodeData {
  label: string;
  spreadsheet_id: string;
  sheet_name: string;
  action: GoogleSheetsAction;
  /** Ordered column ↔ session-variable mappings. */
  column_mappings: GoogleSheetsColumnMapping[];
  /** For read_row: column letter/header to filter on. */
  filter_column: string;
  /** For read_row: value to match (supports {{variable}} interpolation). */
  filter_value: string;
  /** For read_row: session variable to store the matched row dict. */
  result_variable: string;
}

export interface SqlQueryNodeData {
  label: string;
  connection_id: string | null;
  connection_label: string;
  /** Legacy/test-only inline DSN — prefer connection_id from secure storage. */
  connection_string: string;
  query: string;
  result_variable: string;
  max_rows: number;
}

export type MediaProvider = "kling" | "nanobanana";

export type ImageAspectRatio = "1:1" | "16:9" | "9:16";

export interface ImageGenerationNodeData {
  label: string;
  provider: MediaProvider;
  model_name: string;
  prompt_template: string;
  aspect_ratio: ImageAspectRatio;
  result_variable: string;
}

export type FlowNodeData =
  | TriggerNodeData
  | TextMessageNodeData
  | WhatsAppNodeData
  | AIAgentNodeData
  | CRMActionNodeData
  | ConditionNodeData
  | ApiRequestNodeData
  | KnowledgeSearchNodeData
  | LoopNodeData
  | HumanHandoffNodeData
  | GoogleSheetsNodeData
  | SqlQueryNodeData
  | ImageGenerationNodeData;

export type FlowCanvasNode = Node<FlowNodeData>;
export type FlowCanvasEdge = Edge;

/** Spec aliases requested by the Flow Builder contract. */
export type CustomNode = FlowCanvasNode;
export type CustomEdge = FlowCanvasEdge;

export interface TextMessageExportData {
  text: string;
  buttons: FlowButton[];
}

export interface TriggerExportData {
  trigger_type: TriggerType;
  webhook_event?: string;
}

export interface AIAgentExportData {
  prompt_context: string;
  knowledge_base_id: string;
  prompt_modifier?: string;
  temperature?: number;
  model_name?: string;
  llm_model_name?: string;
  variables?: string[];
}

export interface ConditionExportData {
  condition_type: ConditionType;
  tag: string;
  expression: string;
  true_label: string | null;
  false_label: string | null;
}

export interface ApiRequestExportData {
  method: ApiHttpMethod;
  url: string;
  headers: Record<string, string>;
  body_template: string;
  variable_name: string;
  success_label: string | null;
  failure_label: string | null;
}

export interface KnowledgeSearchExportData {
  top_k: number;
  query_variable: string;
  output_variable: string;
  knowledge_base_id?: string;
}

export interface LoopExportData {
  max_iterations: number;
  continue_expression: string;
  body_label: string | null;
  exit_label: string | null;
}

export interface HumanHandoffExportData {
  handoff_message: string;
  queue_tag: string;
  pause_bot: boolean;
}

export interface GoogleSheetsExportData {
  spreadsheet_id: string;
  sheet_name: string;
  action: GoogleSheetsAction;
  column_mapping?: Record<string, string>;
  filter_column?: string;
  filter_value?: string;
  result_variable?: string;
}

export interface SqlQueryExportData {
  connection_id?: string | null;
  connection_label?: string;
  query: string;
  result_variable: string;
  max_rows?: number;
}

export interface ImageGenerationExportData {
  provider: MediaProvider;
  model_name?: string;
  prompt_template: string;
  aspect_ratio?: ImageAspectRatio;
  result_variable: string;
}

/** Exported graph node — matches backend FlowNode schema */
export interface ExportedGraphNode {
  id: string;
  type: BackendNodeType;
  position?: { x: number; y: number };
  data:
    | TriggerExportData
    | TextMessageExportData
    | AIAgentExportData
    | CRMActionExportData
    | ConditionExportData
    | ApiRequestExportData
    | KnowledgeSearchExportData
    | LoopExportData
    | HumanHandoffExportData
    | GoogleSheetsExportData
    | SqlQueryExportData
    | ImageGenerationExportData;
}

export interface ExportedGraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
}

export interface ExportedGraphJSON {
  nodes: ExportedGraphNode[];
  edges: ExportedGraphEdge[];
}

/** Spec alias for the persisted/exported graph payload. */
export type FlowData = ExportedGraphJSON;

export interface PublishFlowPayload {
  title: string;
  graph_data: ExportedGraphJSON;
  is_published: boolean;
}

export interface BotFlowResponse {
  bot_id: string;
  flow_id: string | null;
  title: string;
  graph_data: ExportedGraphJSON;
  is_published: boolean;
  is_default_template: boolean;
  updated_at: string | null;
}

const GRID_X = 280;
const GRID_Y = 160;

export const CANVAS_SNAP_GRID: [number, number] = [20, 20];

export const FLOW_EDGE_TYPE = "smartBezier" as const;

export function importGraphFromJSON(
  graph: ExportedGraphJSON,
): { nodes: FlowCanvasNode[]; edges: FlowCanvasEdge[] } {
  const nodes: FlowCanvasNode[] = [];

  graph.nodes.forEach((node, index) => {
    const canvasType = BACKEND_TO_CANVAS_TYPE[node.type];
    if (!canvasType) {
      return;
    }

    let data: FlowNodeData;
    const fallbackPosition = {
      x: 120 + (index % 3) * GRID_X,
      y: 100 + Math.floor(index / 3) * GRID_Y,
    };
    const position = node.position ?? fallbackPosition;

    if (node.type === "trigger") {
      const triggerData = node.data as TriggerExportData;
      data = {
        label: "Trigger",
        trigger_type: triggerData.trigger_type ?? "message_received",
        webhook_event: triggerData.webhook_event ?? "",
      };
    } else if (node.type === "text_message") {
      const textData = node.data as TextMessageExportData;
      data = {
        label: "Text Message",
        text: textData.text,
        buttons: textData.buttons.map((button) => ({
          id: button.id,
          text: button.text,
        })),
      };
    } else if (node.type === "ai_agent") {
      const aiData = node.data as AIAgentExportData;
      data = {
        label: "LLM",
        prompt_context: aiData.prompt_context,
        knowledge_base_id: aiData.knowledge_base_id,
        prompt_modifier: aiData.prompt_modifier ?? "",
        temperature: aiData.temperature ?? 0.7,
        model_name: aiData.model_name ?? aiData.llm_model_name ?? "gpt-4o-mini",
        variables: aiData.variables ?? [],
      };
    } else if (node.type === "condition") {
      const conditionData = node.data as ConditionExportData;
      data = {
        label: "Condition",
        condition_type: conditionData.condition_type ?? "customer_tag",
        tag: conditionData.tag ?? "",
        expression: conditionData.expression ?? "true",
        true_label: conditionData.true_label ?? "Match",
        false_label: conditionData.false_label ?? "Else",
      };
    } else if (node.type === "api_request") {
      const apiData = node.data as ApiRequestExportData;
      data = {
        label: "API Request",
        method: apiData.method ?? "POST",
        url: apiData.url ?? "",
        headers: apiData.headers ?? {},
        body_template: apiData.body_template ?? "",
        variable_name: apiData.variable_name ?? "api_response",
        success_label: apiData.success_label ?? "Success",
        failure_label: apiData.failure_label ?? "Failure",
      };
    } else if (node.type === "knowledge_search") {
      const searchData = node.data as KnowledgeSearchExportData;
      data = {
        label: "Knowledge Search",
        top_k: searchData.top_k ?? 3,
        query_variable: searchData.query_variable ?? "message",
        output_variable: searchData.output_variable ?? "rag_context",
        knowledge_base_id: searchData.knowledge_base_id ?? "",
      };
    } else if (node.type === "crm_action") {
      const crmData = node.data as CRMActionExportData;
      const tags = crmData.params?.tags ?? [];
      const integration = (crmData.integration_type ||
        crmData.action_type ||
        crmData.params?.platform ||
        "custom_webhook") as CRMIntegrationType;
      const normalizedIntegration: CRMIntegrationType =
        integration === "amocrm" || integration === "bitrix24" || integration === "custom_webhook"
          ? integration
          : "custom_webhook";
      const platform =
        normalizedIntegration === "bitrix24"
          ? "bitrix24"
          : normalizedIntegration === "amocrm"
            ? "amocrm"
            : (crmData.params?.platform ?? "amocrm");
      data = {
        label: "CRM Action",
        integration_type: normalizedIntegration,
        method: crmData.method ?? "POST",
        url: crmData.url ?? "",
        headers: recordToHeaders(crmData.headers),
        body_template:
          crmData.body_template ??
          '{\n  "phone": "{{phone}}",\n  "lead_name": "Lead from WhatsApp"\n}',
        response_variable: crmData.response_variable ?? "crm_result",
        action_type: normalizedIntegration,
        platform,
        pipeline_id: crmData.params?.pipeline_id ?? "",
        stage_id: crmData.params?.stage_id ?? "",
        tags: tags.join(", "),
        params: {
          platform,
          pipeline_id: crmData.params?.pipeline_id ?? "",
          stage_id: crmData.params?.stage_id ?? "",
          tags,
        },
      };
    } else if (node.type === "loop") {
      const loopData = node.data as LoopExportData;
      data = {
        label: "Loop",
        max_iterations: loopData.max_iterations ?? 5,
        continue_expression: loopData.continue_expression ?? "true",
        body_label: loopData.body_label ?? "Body",
        exit_label: loopData.exit_label ?? "Exit",
      };
    } else if (node.type === "human_handoff") {
      const handoffData = node.data as HumanHandoffExportData;
      data = {
        label: "Human Handoff",
        handoff_message:
          handoffData.handoff_message ??
          "Connecting you with an operator. Please wait…",
        queue_tag: handoffData.queue_tag ?? "",
        pause_bot: handoffData.pause_bot ?? true,
      };
    } else if (node.type === "google_sheets") {
      const sheetsData = node.data as GoogleSheetsExportData;
      data = {
        label: "Google Sheets",
        spreadsheet_id: sheetsData.spreadsheet_id ?? "",
        sheet_name: sheetsData.sheet_name ?? "Sheet1",
        action: sheetsData.action ?? "append_row",
        column_mappings: Object.entries(sheetsData.column_mapping ?? {}).map(
          ([column_key, variable_name]) => ({ column_key, variable_name }),
        ),
        filter_column: sheetsData.filter_column ?? "A",
        filter_value: sheetsData.filter_value ?? "",
        result_variable: sheetsData.result_variable ?? "sheet_result",
      };
    } else if (node.type === "sql_query") {
      const sqlData = node.data as SqlQueryExportData;
      data = {
        label: "SQL Query",
        connection_id: sqlData.connection_id ?? null,
        connection_label: sqlData.connection_label ?? "",
        connection_string: "",
        query: sqlData.query ?? "SELECT 1",
        result_variable: sqlData.result_variable ?? "sql_result",
        max_rows: sqlData.max_rows ?? 50,
      };
    } else if (node.type === "image_generation") {
      const imageData = node.data as ImageGenerationExportData;
      data = {
        label: "Image Generation",
        provider: imageData.provider ?? "kling",
        model_name: imageData.model_name ?? "",
        prompt_template: imageData.prompt_template ?? "",
        aspect_ratio: imageData.aspect_ratio ?? "1:1",
        result_variable: imageData.result_variable ?? "generated_image_url",
      };
    } else {
      return;
    }

    nodes.push({
      id: node.id,
      type: canvasType,
      position,
      data,
    });
  });

  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: FlowCanvasEdge[] = graph.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      type: FLOW_EDGE_TYPE,
    }));

  return { nodes, edges };
}

export const CANVAS_TO_BACKEND_TYPE: Record<CanvasNodeType, BackendNodeType> = {
  trigger: "trigger",
  textMessage: "text_message",
  whatsapp: "text_message",
  condition: "condition",
  aiAgent: "ai_agent",
  llm: "ai_agent",
  knowledgeSearch: "knowledge_search",
  rag: "knowledge_search",
  crmAction: "crm_action",
  crm: "crm_action",
  apiRequest: "api_request",
  loop: "loop",
  humanHandoff: "human_handoff",
  googleSheets: "google_sheets",
  sqlQuery: "sql_query",
  imageGeneration: "image_generation",
};

export const BACKEND_TO_CANVAS_TYPE: Record<BackendNodeType, CanvasNodeType | null> = {
  trigger: "trigger",
  text_message: "textMessage",
  condition: "condition",
  ai_agent: "aiAgent",
  knowledge_search: "knowledgeSearch",
  crm_action: "crmAction",
  api_request: "apiRequest",
  loop: "loop",
  human_handoff: "humanHandoff",
  google_sheets: "googleSheets",
  sql_query: "sqlQuery",
  image_generation: "imageGeneration",
};

export const NODE_PALETTE_ITEMS: Array<{
  type: CanvasNodeType;
  label: string;
  description: string;
}> = [
  {
    type: "trigger",
    label: "Trigger",
    description: "Start on message, webhook, or manual run",
  },
  {
    type: "textMessage",
    label: "Text Message",
    description: "Send a message with inline reply buttons",
  },
  {
    type: "whatsapp",
    label: "WhatsApp",
    description: "WhatsApp outbound template (+ optional media)",
  },
  {
    type: "condition",
    label: "Condition / If-Else",
    description: "Split by tags, working hours, or expressions",
  },
  {
    type: "loop",
    label: "Loop",
    description: "Repeat a subgraph until exit or max iterations",
  },
  {
    type: "rag",
    label: "RAG / Knowledge",
    description: "Chroma RAG retrieval → {{rag_context}} for LLM",
  },
  {
    type: "aiAgent",
    label: "LLM",
    description: "System prompt, temperature, and variable insertion",
  },
  {
    type: "apiRequest",
    label: "API Call",
    description: "Webhook GET/POST with success/failure branches",
  },
  {
    type: "crmAction",
    label: "CRM Action",
    description: "Custom webhook, amoCRM, or Bitrix24 HTTP calls",
  },
  {
    type: "humanHandoff",
    label: "Human Handoff",
    description: "Pause bot and transfer chat to an operator",
  },
  {
    type: "googleSheets",
    label: "Google Sheets",
    description: "Append or read rows in a Google Spreadsheet",
  },
  {
    type: "sqlQuery",
    label: "SQL Query",
    description: "Run a read-only SELECT query against an external database",
  },
  {
    type: "imageGeneration",
    label: "Image Generation",
    description: "Generate images via Kling AI or Nano Banana Pro",
  },
];

export function isTriggerData(data: FlowNodeData): data is TriggerNodeData {
  return "trigger_type" in data;
}

export function isWhatsAppData(data: FlowNodeData): data is WhatsAppNodeData {
  return "channel" in data && (data as WhatsAppNodeData).channel === "whatsapp";
}

export function isTextMessageData(data: FlowNodeData): data is TextMessageNodeData {
  return "text" in data && "buttons" in data && !isWhatsAppData(data);
}

export function isAIAgentData(data: FlowNodeData): data is AIAgentNodeData {
  return "prompt_context" in data && "knowledge_base_id" in data;
}

export function isCRMActionData(data: FlowNodeData): data is CRMActionNodeData {
  if ("integration_type" in data && "response_variable" in data) {
    return true;
  }
  return "platform" in data && "params" in data && "stage_id" in data;
}

export function isConditionData(data: FlowNodeData): data is ConditionNodeData {
  return "condition_type" in data && "true_label" in data && "false_label" in data;
}

export function isApiRequestData(data: FlowNodeData): data is ApiRequestNodeData {
  return "method" in data && "url" in data && "variable_name" in data;
}

export function isKnowledgeSearchData(data: FlowNodeData): data is KnowledgeSearchNodeData {
  return "top_k" in data && "query_variable" in data && "output_variable" in data;
}

export function isLoopData(data: FlowNodeData): data is LoopNodeData {
  return "max_iterations" in data && "continue_expression" in data && "body_label" in data;
}

export function isHumanHandoffData(data: FlowNodeData): data is HumanHandoffNodeData {
  return "handoff_message" in data && "pause_bot" in data;
}

export function isGoogleSheetsData(data: FlowNodeData): data is GoogleSheetsNodeData {
  return "spreadsheet_id" in data && "action" in data && "column_mappings" in data;
}

export function isSqlQueryData(data: FlowNodeData): data is SqlQueryNodeData {
  return "query" in data && "result_variable" in data && "max_rows" in data;
}

export function isImageGenerationData(
  data: FlowNodeData,
): data is ImageGenerationNodeData {
  return "provider" in data && "prompt_template" in data && "aspect_ratio" in data;
}

/**
 * Connection validation rules for React Flow ``isValidConnection``.
 * Prevents self-loops and duplicate edges; enforces handle cardinality lightly.
 */
export function isValidFlowConnection(
  connection: { source?: string | null; target?: string | null; sourceHandle?: string | null },
  edges: FlowCanvasEdge[],
): boolean {
  const { source, target, sourceHandle } = connection;
  if (!source || !target || source === target) {
    return false;
  }
  return !edges.some(
    (edge) =>
      edge.source === source &&
      edge.target === target &&
      (edge.sourceHandle ?? null) === (sourceHandle ?? null),
  );
}

export function createDefaultNodeData(type: CanvasNodeType): FlowNodeData {
  if (type === "trigger") {
    return {
      label: "Trigger",
      trigger_type: "message_received",
      webhook_event: "",
    };
  }

  if (type === "textMessage") {
    return {
      label: "Text Message",
      text: "",
      buttons: [],
    };
  }

  if (type === "whatsapp") {
    return {
      label: "WhatsApp",
      text: "",
      buttons: [],
      media_url: "",
      channel: "whatsapp",
    };
  }

  if (type === "condition") {
    return {
      label: "Condition",
      condition_type: "customer_tag",
      tag: "",
      expression: "true",
      true_label: "Match",
      false_label: "Else",
    };
  }

  if (type === "loop") {
    return {
      label: "Loop",
      max_iterations: 5,
      continue_expression: "true",
      body_label: "Body",
      exit_label: "Exit",
    };
  }

  if (type === "humanHandoff") {
    return {
      label: "Human Handoff",
      handoff_message: "Connecting you with an operator. Please wait…",
      queue_tag: "general",
      pause_bot: true,
    };
  }

  if (type === "knowledgeSearch" || type === "rag") {
    return {
      label: type === "rag" ? "RAG" : "Knowledge Search",
      top_k: 3,
      query_variable: "message",
      output_variable: "rag_context",
      knowledge_base_id: "",
    };
  }

  if (type === "apiRequest") {
    return {
      label: "API Call",
      method: "POST",
      url: "",
      headers: {},
      body_template: '{"message":"{{message}}"}',
      variable_name: "api_response",
      success_label: "Success",
      failure_label: "Failure",
    };
  }

  if (type === "crmAction" || type === "crm") {
    return {
      label: "CRM Action",
      integration_type: "custom_webhook",
      method: "POST",
      url: "",
      headers: [
        { id: "h-content-type", key: "Content-Type", value: "application/json" },
      ],
      body_template:
        '{\n  "phone": "{{phone}}",\n  "lead_name": "Lead from WhatsApp"\n}',
      response_variable: "crm_result",
      action_type: "custom_webhook",
      platform: "amocrm",
      pipeline_id: "",
      stage_id: "",
      tags: "",
      params: {
        platform: "amocrm",
        pipeline_id: "",
        stage_id: "",
        tags: [],
      },
    };
  }

  if (type === "googleSheets") {
    return {
      label: "Google Sheets",
      spreadsheet_id: "",
      sheet_name: "Sheet1",
      action: "append_row",
      column_mappings: [],
      filter_column: "A",
      filter_value: "",
      result_variable: "sheet_result",
    };
  }

  if (type === "sqlQuery") {
    return {
      label: "SQL Query",
      connection_id: null,
      connection_label: "",
      connection_string: "",
      query: "SELECT * FROM products WHERE sku = {{ session.variables.user_sku }}",
      result_variable: "sql_result",
      max_rows: 50,
    };
  }

  if (type === "imageGeneration") {
    return {
      label: "Image Generation",
      provider: "kling",
      model_name: "kling-v1",
      prompt_template:
        "Professional product photo of {{ session.variables.product_name }} on a clean background",
      aspect_ratio: "1:1",
      result_variable: "generated_image_url",
    };
  }

  return {
    label: "LLM",
    prompt_context: "",
    knowledge_base_id: "kb_faq_support",
    prompt_modifier: "",
    temperature: 0.7,
    model_name: "gpt-4o-mini",
    variables: [],
  };
}
