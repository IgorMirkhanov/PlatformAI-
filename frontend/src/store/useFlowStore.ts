import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "reactflow";
import { create } from "zustand";
import { persist } from "zustand/middleware";

import { ApiError, fetchBotFlow, fetchBotHealth, publishBotFlow, saveBotFlow } from "@/lib/api";
import { autoLayoutGraph } from "@/lib/flowAutoLayout";
import {
  validateFlowGraph,
  type GraphValidationIssue,
} from "@/lib/validateFlowGraph";
import { generateId } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import {
  CANVAS_TO_BACKEND_TYPE,
  createDefaultNodeData,
  importGraphFromJSON,
  type AIAgentExportData,
  type ApiRequestExportData,
  type CanvasNodeType,
  type ConditionExportData,
  type ExportedGraphEdge,
  type ExportedGraphJSON,
  type ExportedGraphNode,
  type FlowCanvasEdge,
  type FlowCanvasNode,
  type FlowNodeData,
  FLOW_EDGE_TYPE,
  type HumanHandoffExportData,
  type ImageGenerationExportData,
  isAIAgentData,
  isApiRequestData,
  isConditionData,
  isCRMActionData,
  isGoogleSheetsData,
  isHumanHandoffData,
  isImageGenerationData,
  isKnowledgeSearchData,
  isLoopData,
  isSqlQueryData,
  isTextMessageData,
  isTriggerData,
  isValidFlowConnection,
  isWhatsAppData,
  type KnowledgeSearchExportData,
  type LoopExportData,
  type PublishFlowPayload,
  type SqlQueryExportData,
  type TextMessageExportData,
  type TriggerExportData,
} from "@/types/flow";
import type { CRMActionExportData } from "@/types/crm";
import { headersToRecord } from "@/types/crm";

export type { GraphValidationIssue };
export type PublishStatus = "idle" | "loading" | "success" | "error";
export type LoadStatus = "idle" | "loading" | "success" | "error";
export type SaveStatus = "idle" | "loading" | "success" | "error";

const HISTORY_LIMIT = 20;

interface GraphSnapshot {
  nodes: FlowCanvasNode[];
  edges: FlowCanvasEdge[];
}

interface FlowState {
  nodes: FlowCanvasNode[];
  edges: FlowCanvasEdge[];
  selectedNode: FlowCanvasNode | null;
  publishStatus: PublishStatus;
  publishError: string | null;
  publishIssues: GraphValidationIssue[];
  invalidNodeIds: string[];
  lastPublishedFlowId: string | null;
  saveStatus: SaveStatus;
  saveError: string | null;
  loadStatus: LoadStatus;
  loadError: string | null;
  loadedBotId: string | null;
  snapToGrid: boolean;
  showGrid: boolean;
  past: GraphSnapshot[];
  future: GraphSnapshot[];
  /** Pre-drag graph captured on ``onNodeDragStart``; committed on ``onNodeDragStop``. */
  dragSnapshot: GraphSnapshot | null;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  onNodeDragStart: () => void;
  onNodeDragStop: () => void;
  addNode: (type: string, position?: { x: number; y: number }) => void;
  deleteNode: (id: string) => void;
  /** @deprecated Prefer ``deleteNode`` — kept for existing node wrappers. */
  removeNode: (nodeId: string) => void;
  updateNodeData: (nodeId: string, data: Partial<FlowNodeData>) => void;
  setGraph: (nodes: FlowCanvasNode[], edges: FlowCanvasEdge[]) => void;
  setSelectedNode: (node: FlowCanvasNode | null) => void;
  exportGraphJSON: () => ExportedGraphJSON;
  validateGraphLocally: () => GraphValidationIssue[];
  runGraphValidation: () => GraphValidationIssue[];
  clearValidationHighlights: () => void;
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
  saveFlow: (botId: string, title: string) => Promise<void>;
  publishFlow: (botId: string, title: string) => Promise<void>;
  loadPublishedFlow: (botId: string) => Promise<void>;
  resetPublishState: () => void;
  resetSelection: () => void;
  setSnapToGrid: (enabled: boolean) => void;
  setShowGrid: (enabled: boolean) => void;
  autoLayout: () => void;
  exportJSONDownload: () => void;
}

function cloneSnapshot(nodes: FlowCanvasNode[], edges: FlowCanvasEdge[]): GraphSnapshot {
  return {
    nodes: structuredClone(nodes),
    edges: structuredClone(edges),
  };
}

function shouldRecordNodeHistory(changes: NodeChange[]): boolean {
  // Position history is handled by onNodeDragStart / onNodeDragStop so we do not
  // clone the full graph on every drag frame.
  return changes.some((change) => change.type === "remove" || change.type === "add");
}

function shouldRecordEdgeHistory(changes: EdgeChange[]): boolean {
  return changes.some((change) => change.type === "remove" || change.type === "add");
}

function toExportedNode(node: FlowCanvasNode): ExportedGraphNode | null {
  const backendType = CANVAS_TO_BACKEND_TYPE[node.type as CanvasNodeType];
  if (!backendType) {
    return null;
  }

  const position = { x: node.position.x, y: node.position.y };

  if (node.type === "trigger" && isTriggerData(node.data)) {
    const data: TriggerExportData = {
      trigger_type: node.data.trigger_type,
      webhook_event: node.data.webhook_event.trim() || undefined,
    };
    return { id: node.id, type: "trigger", position, data };
  }

  if (node.type === "textMessage" && isTextMessageData(node.data)) {
    const data: TextMessageExportData = {
      text: node.data.text.trim() || " ",
      buttons: node.data.buttons.map((button) => ({
        id: button.id,
        text: button.text,
      })),
    };

    return {
      id: node.id,
      type: "text_message",
      position,
      data,
    };
  }

  if (node.type === "whatsapp" && isWhatsAppData(node.data)) {
    const data: TextMessageExportData = {
      text: node.data.text.trim() || " ",
      buttons: (node.data.buttons ?? []).map((button) => ({
        id: button.id,
        text: button.text,
      })),
    };
    return {
      id: node.id,
      type: "text_message",
      position,
      data: {
        ...data,
        // Extra metadata consumed by executor variables / outbound adapters
        channel: "whatsapp",
        media_url: node.data.media_url || undefined,
      } as TextMessageExportData,
    };
  }

  if (
    (node.type === "aiAgent" || node.type === "llm") &&
    isAIAgentData(node.data)
  ) {
    const modelName = (node.data.model_name || "gpt-4o-mini").trim();
    const data: AIAgentExportData = {
      prompt_context: node.data.prompt_context.trim() || "You are a helpful assistant.",
      knowledge_base_id: node.data.knowledge_base_id.trim() || "default_kb",
      prompt_modifier: node.data.prompt_modifier.trim() || undefined,
      temperature: node.data.temperature ?? 0.7,
      model_name: modelName,
      llm_model_name: modelName,
      variables: node.data.variables ?? [],
    };

    return {
      id: node.id,
      type: "ai_agent",
      position,
      data,
    };
  }

  if (node.type === "condition" && isConditionData(node.data)) {
    const data: ConditionExportData = {
      condition_type: node.data.condition_type,
      tag: node.data.tag.trim(),
      expression: node.data.expression.trim() || "true",
      true_label: node.data.true_label,
      false_label: node.data.false_label,
    };

    return {
      id: node.id,
      type: "condition",
      position,
      data,
    };
  }

  if (node.type === "apiRequest" && isApiRequestData(node.data)) {
    const data: ApiRequestExportData = {
      method: node.data.method,
      url: node.data.url.trim() || "https://example.com/webhook",
      headers: node.data.headers,
      body_template: node.data.body_template,
      variable_name: node.data.variable_name.trim() || "api_response",
      success_label: node.data.success_label,
      failure_label: node.data.failure_label,
    };

    return {
      id: node.id,
      type: "api_request",
      position,
      data,
    };
  }

  if (
    (node.type === "knowledgeSearch" || node.type === "rag") &&
    isKnowledgeSearchData(node.data)
  ) {
    const data: KnowledgeSearchExportData = {
      top_k: Math.max(1, Math.min(10, Number(node.data.top_k) || 3)),
      query_variable: node.data.query_variable.trim() || "message",
      output_variable: node.data.output_variable.trim() || "rag_context",
      knowledge_base_id: node.data.knowledge_base_id.trim() || undefined,
    };

    return {
      id: node.id,
      type: "knowledge_search",
      position,
      data,
    };
  }

  if (
    (node.type === "crmAction" || node.type === "crm") &&
    isCRMActionData(node.data)
  ) {
    const integration =
      node.data.integration_type ||
      (node.data.action_type as typeof node.data.integration_type) ||
      "custom_webhook";
    const data: CRMActionExportData = {
      action_type: integration,
      integration_type: integration,
      method: node.data.method || "POST",
      url: (node.data.url || "").trim(),
      headers: headersToRecord(node.data.headers || []),
      body_template: node.data.body_template || "",
      response_variable: (node.data.response_variable || "crm_result").trim() || "crm_result",
      params: {
        platform: node.data.params?.platform ?? node.data.platform ?? "amocrm",
        pipeline_id: node.data.params?.pipeline_id ?? node.data.pipeline_id ?? "",
        stage_id: node.data.params?.stage_id ?? node.data.stage_id ?? "",
        tags: node.data.params?.tags ?? [],
      },
    };

    return {
      id: node.id,
      type: "crm_action",
      position,
      data,
    };
  }

  if (node.type === "loop" && isLoopData(node.data)) {
    const data: LoopExportData = {
      max_iterations: Math.max(1, Number(node.data.max_iterations) || 5),
      continue_expression: node.data.continue_expression.trim() || "true",
      body_label: node.data.body_label,
      exit_label: node.data.exit_label,
    };
    return { id: node.id, type: "loop", position, data };
  }

  if (node.type === "humanHandoff" && isHumanHandoffData(node.data)) {
    const data: HumanHandoffExportData = {
      handoff_message:
        node.data.handoff_message.trim() ||
        "Connecting you with an operator. Please wait…",
      queue_tag: node.data.queue_tag.trim(),
      pause_bot: Boolean(node.data.pause_bot),
    };
    return { id: node.id, type: "human_handoff", position, data };
  }

  if (node.type === "googleSheets" && isGoogleSheetsData(node.data)) {
    const data = {
      spreadsheet_id: node.data.spreadsheet_id.trim(),
      sheet_name: node.data.sheet_name.trim() || "Sheet1",
      action: node.data.action,
      column_mapping: Object.fromEntries(
        node.data.column_mappings
          .filter((item) => item.column_key.trim() && item.variable_name.trim())
          .map((item) => [item.column_key.trim(), item.variable_name.trim()]),
      ),
      filter_column: node.data.filter_column.trim() || "A",
      filter_value: node.data.filter_value,
      result_variable: node.data.result_variable.trim() || "sheet_result",
    };
    return { id: node.id, type: "google_sheets", position, data };
  }

  if (node.type === "sqlQuery" && isSqlQueryData(node.data)) {
    const data: SqlQueryExportData = {
      connection_id: node.data.connection_id || null,
      connection_label: node.data.connection_label.trim() || undefined,
      query: node.data.query.trim() || "SELECT 1",
      result_variable: node.data.result_variable.trim() || "sql_result",
      max_rows: Math.max(1, Math.min(500, Number(node.data.max_rows) || 50)),
    };
    return { id: node.id, type: "sql_query", position, data };
  }

  if (node.type === "imageGeneration" && isImageGenerationData(node.data)) {
    const data: ImageGenerationExportData = {
      provider: node.data.provider,
      model_name: node.data.model_name.trim() || undefined,
      prompt_template: node.data.prompt_template.trim(),
      aspect_ratio: node.data.aspect_ratio,
      result_variable: node.data.result_variable.trim() || "generated_image_url",
    };
    return { id: node.id, type: "image_generation", position, data };
  }

  return null;
}

function toExportedEdge(edge: FlowCanvasEdge): ExportedGraphEdge {
  const exported: ExportedGraphEdge = {
    id: edge.id,
    source: edge.source,
    target: edge.target,
  };

  if (edge.sourceHandle) {
    exported.sourceHandle = edge.sourceHandle;
  }

  return exported;
}

export const useFlowStore = create<FlowState>()(
  persist(
    (set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  publishStatus: "idle",
  publishError: null,
  publishIssues: [],
  invalidNodeIds: [],
  lastPublishedFlowId: null,
  saveStatus: "idle",
  saveError: null,
  loadStatus: "idle",
  loadError: null,
  loadedBotId: null,
  snapToGrid: true,
  showGrid: true,
  past: [],
  future: [],
  dragSnapshot: null,

  pushHistory: () => {
    const { nodes, edges, past } = get();
    const nextPast = [...past, cloneSnapshot(nodes, edges)].slice(-HISTORY_LIMIT);
    set({ past: nextPast, future: [], dragSnapshot: null });
  },

  onNodeDragStart: () => {
    const { nodes, edges } = get();
    set({ dragSnapshot: cloneSnapshot(nodes, edges) });
  },

  onNodeDragStop: () => {
    const { dragSnapshot, past, nodes } = get();
    if (!dragSnapshot) return;

    const before = dragSnapshot.nodes;
    const moved = before.some((node) => {
      const current = nodes.find((item) => item.id === node.id);
      if (!current) return true;
      return current.position.x !== node.position.x || current.position.y !== node.position.y;
    });

    if (!moved) {
      set({ dragSnapshot: null });
      return;
    }

    set({
      past: [...past, dragSnapshot].slice(-HISTORY_LIMIT),
      future: [],
      dragSnapshot: null,
    });
  },

  undo: () => {
    const { past, nodes, edges, future } = get();
    if (past.length === 0) return;
    const previous = past[past.length - 1];
    set({
      past: past.slice(0, -1),
      future: [cloneSnapshot(nodes, edges), ...future].slice(0, HISTORY_LIMIT),
      nodes: previous.nodes,
      edges: previous.edges,
      selectedNode: null,
      invalidNodeIds: [],
    });
  },

  redo: () => {
    const { future, nodes, edges, past } = get();
    if (future.length === 0) return;
    const next = future[0];
    set({
      future: future.slice(1),
      past: [...past, cloneSnapshot(nodes, edges)].slice(-HISTORY_LIMIT),
      nodes: next.nodes,
      edges: next.edges,
      selectedNode: null,
      invalidNodeIds: [],
    });
  },

  canUndo: () => get().past.length > 0,
  canRedo: () => get().future.length > 0,

  clearValidationHighlights: () => {
    set({ invalidNodeIds: [], publishIssues: [] });
  },

  runGraphValidation: () => {
    const result = validateFlowGraph(get().nodes, get().edges);
    if (!result.ok) {
      set({
        publishIssues: result.issues,
        invalidNodeIds: result.invalidNodeIds,
        publishError: result.issues[0]?.message ?? "Ошибка валидации графа.",
        publishStatus: "error",
      });
      return result.issues;
    }

    const publishStatus = get().publishStatus === "error" ? "idle" : get().publishStatus;
    set({
      publishIssues: [],
      invalidNodeIds: [],
      publishError: null,
      publishStatus,
    });
    return [];
  },

  onNodesChange: (changes: NodeChange[]) => {
    if (shouldRecordNodeHistory(changes)) {
      get().pushHistory();
    }
    set({
      nodes: applyNodeChanges(changes, get().nodes) as FlowCanvasNode[],
    });
  },

  onEdgesChange: (changes: EdgeChange[]) => {
    if (shouldRecordEdgeHistory(changes)) {
      get().pushHistory();
    }
    set({
      edges: applyEdgeChanges(changes, get().edges),
    });
  },

  onConnect: (connection: Connection) => {
    if (!isValidFlowConnection(connection, get().edges)) {
      return;
    }
    get().pushHistory();
    set({
      edges: addEdge(
        {
          ...connection,
          id: generateId("edge"),
          type: FLOW_EDGE_TYPE,
        },
        get().edges,
      ),
    });
  },

  addNode: (type: string, position?: { x: number; y: number }) => {
    get().pushHistory();
    const canvasType = type as CanvasNodeType;
    const prefixMap: Record<CanvasNodeType, string> = {
      trigger: "trigger",
      textMessage: "text_message",
      whatsapp: "whatsapp",
      condition: "condition",
      aiAgent: "ai_agent",
      llm: "llm",
      knowledgeSearch: "knowledge_search",
      rag: "rag",
      apiRequest: "api_request",
      crmAction: "crm_action",
      crm: "crm",
      googleSheets: "google_sheets",
      sqlQuery: "sql_query",
      imageGeneration: "image_generation",
      loop: "loop",
      humanHandoff: "human_handoff",
    };
    const nodeId = generateId(prefixMap[canvasType] ?? "node");

    const newNode: FlowCanvasNode = {
      id: nodeId,
      type: canvasType,
      position: position ?? {
        x: 120 + get().nodes.length * 40,
        y: 100 + get().nodes.length * 40,
      },
      data: createDefaultNodeData(canvasType),
    };

    set({ nodes: [...get().nodes, newNode] });
  },

  deleteNode: (id: string) => {
    get().pushHistory();
    const selectedNode = get().selectedNode;
    set({
      nodes: get().nodes.filter((node) => node.id !== id),
      edges: get().edges.filter(
        (edge) => edge.source !== id && edge.target !== id,
      ),
      selectedNode: selectedNode?.id === id ? null : selectedNode,
      invalidNodeIds: get().invalidNodeIds.filter((nodeId) => nodeId !== id),
    });
  },

  removeNode: (nodeId: string) => {
    get().deleteNode(nodeId);
  },

  updateNodeData: (nodeId: string, data: Partial<FlowNodeData>) => {
    const current = get().nodes.find((node) => node.id === nodeId);
    if (!current) return;

    const nextData = { ...current.data, ...data } as FlowNodeData;
    // Skip no-op patches (avoids history spam from identical commits).
    if (JSON.stringify(current.data) === JSON.stringify(nextData)) {
      return;
    }

    get().pushHistory();
    const currentSelected = get().selectedNode;

    set({
      nodes: get().nodes.map((node) => {
        if (node.id !== nodeId) {
          return node;
        }

        return {
          ...node,
          data: nextData,
        };
      }),
      selectedNode:
        currentSelected?.id === nodeId
          ? ({
              ...currentSelected,
              data: nextData,
            } as FlowCanvasNode)
          : currentSelected,
    });
  },

  setGraph: (nodes: FlowCanvasNode[], edges: FlowCanvasEdge[]) => {
    set({
      nodes,
      edges,
      selectedNode: null,
      past: [],
      future: [],
      dragSnapshot: null,
      invalidNodeIds: [],
      publishIssues: [],
    });
  },

  setSelectedNode: (node: FlowCanvasNode | null) => {
    set({ selectedNode: node });
  },

  resetSelection: () => {
    set({ selectedNode: null });
  },

  setSnapToGrid: (enabled: boolean) => {
    set({ snapToGrid: enabled });
  },

  setShowGrid: (enabled: boolean) => {
    set({ showGrid: enabled });
  },

  resetPublishState: () => {
    set({
      publishStatus: "idle",
      publishError: null,
      publishIssues: [],
      invalidNodeIds: [],
    });
  },

  exportGraphJSON: (): ExportedGraphJSON => {
    const { nodes, edges } = get();

    const exportedNodes = nodes
      .map(toExportedNode)
      .filter((node): node is ExportedGraphNode => node !== null);

    const exportedEdges = edges.map(toExportedEdge);

    return {
      nodes: exportedNodes,
      edges: exportedEdges,
    };
  },

  saveFlow: async (botId: string, title: string): Promise<void> => {
    set({ saveStatus: "loading", saveError: null });

    const graphData = get().exportGraphJSON();

    try {
      const response = await saveBotFlow(botId, {
        title,
        nodes: graphData.nodes,
        edges: graphData.edges,
        is_published: false,
      });

      set({
        saveStatus: "success",
        saveError: null,
        lastPublishedFlowId: response.flow_id,
        loadedBotId: botId,
      });

      window.setTimeout(() => {
        set({ saveStatus: "idle" });
      }, 3000);
    } catch (error) {
      set({
        saveStatus: "error",
        saveError:
          error instanceof ApiError
            ? error.message
            : "Failed to save flow. Check that the backend is running.",
      });
    }
  },

  validateGraphLocally: (): GraphValidationIssue[] => {
    return get().runGraphValidation();
  },

  loadPublishedFlow: async (botId: string): Promise<void> => {
    set({
      loadStatus: "loading",
      loadError: null,
    });

    try {
      const flow = await fetchBotFlow(botId);
      const { nodes, edges } = importGraphFromJSON(flow.graph_data);

      get().setGraph(nodes, edges);
      set({
        loadStatus: "success",
        loadedBotId: botId,
        loadError: null,
        lastPublishedFlowId: flow.flow_id,
      });
    } catch (error) {
      set({
        loadStatus: "error",
        loadError:
          error instanceof ApiError
            ? error.message
            : "Failed to load published flow. Check that the backend is running.",
      });
    }
  },

  publishFlow: async (botId: string, title: string): Promise<void> => {
    const localIssues = get().runGraphValidation();
    if (localIssues.length > 0) {
      set({
        publishStatus: "error",
        publishError: localIssues.map((issue) => issue.message).join(" "),
        publishIssues: localIssues,
      });
      return;
    }

    set({
      publishStatus: "loading",
      publishError: null,
      publishIssues: [],
      invalidNodeIds: [],
    });

    const graphData = get().exportGraphJSON();
    const payload: PublishFlowPayload = {
      title,
      graph_data: graphData,
      is_published: true,
    };

    try {
      const response = await publishBotFlow(botId, payload);
      set({
        publishStatus: "success",
        lastPublishedFlowId: response.flow_id,
        publishError: null,
        publishIssues: [],
      });

      try {
        const health = await fetchBotHealth(botId);
        const { connection, updateHealth } = useBotStore.getState();
        if (connection?.botId === botId) {
          updateHealth(health);
        }
      } catch {
        // health refresh is best-effort after publish
      }

      window.setTimeout(() => {
        set({ publishStatus: "idle" });
      }, 4000);
    } catch (error) {
      if (error instanceof ApiError) {
        set({
          publishStatus: "error",
          publishError: error.message,
          publishIssues: error.issues.map((issue) => ({
            code: issue.code,
            message: issue.message,
            nodeId: issue.node_id ?? undefined,
            edgeId: issue.edge_id ?? undefined,
            buttonId: issue.button_id ?? undefined,
          })),
        });
        return;
      }

      set({
        publishStatus: "error",
        publishError: "Failed to publish flow. Check that the backend is running.",
        publishIssues: [],
      });
    }
  },

  autoLayout: () => {
    get().pushHistory();
    const { nodes, edges } = get();
    set({ nodes: autoLayoutGraph(nodes, edges) });
  },

  exportJSONDownload: () => {
    const graph = get().exportGraphJSON();
    const blob = new Blob([JSON.stringify(graph, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `flow-${get().loadedBotId ?? "draft"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  },
    }),
    {
      name: "mpai-flow-builder",
      partialize: (state) => ({
        nodes: state.nodes,
        edges: state.edges,
        loadedBotId: state.loadedBotId,
        snapToGrid: state.snapToGrid,
        showGrid: state.showGrid,
      }),
    },
  ),
);

export type { FlowState };
