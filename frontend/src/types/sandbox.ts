export interface TraceNodeStep {
  node_id: string;
  node_type: string;
  label?: string | null;
}

export interface TraceTransition {
  from_node_id: string;
  to_node_id: string;
  via_handle?: string | null;
  edge_id?: string | null;
}

export interface RAGChunkTrace {
  text: string;
  similarity_score: number;
  document_id?: string | null;
  file_name?: string | null;
  chunk_index?: number | null;
}

export interface LLMMetricsTrace {
  model_name: string;
  system_prompt: string;
  user_query: string;
  raw_response: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_kzt: number;
  temperature: number;
  cache_hit?: boolean;
}

export interface ExecutionTrace {
  nodes_triggered: TraceNodeStep[];
  transitions: TraceTransition[];
  rag_context: RAGChunkTrace[];
  llm_metrics: LLMMetricsTrace | null;
  errors: string[];
  simulation: boolean;
  current_node_id?: string | null;
}

export interface SandboxChatMessage {
  id: string;
  role: "user" | "bot" | "system";
  text: string;
  timestamp: number;
  pending?: boolean;
}

export interface SandboxMessageRequest {
  text: string;
  session_id?: string | null;
}

export interface SandboxChatResponse {
  message: string;
  trace: ExecutionTrace;
  session_id: string;
  current_step_id?: string | null;
}

export interface SandboxWsInbound {
  type: "message";
  text: string;
  session_id?: string | null;
}

export interface SandboxWsOutbound {
  type?: "response" | "error";
  message: string;
  trace: ExecutionTrace;
  session_id: string;
  current_step_id?: string | null;
  error?: string | null;
}

export interface SandboxClearResponse {
  bot_id: string;
  session_id: string;
  cleared: boolean;
  message: string;
}

export type SandboxTraceTab = "graph" | "rag" | "tokens";

export interface SandboxConnectionState {
  connected: boolean;
  connecting: boolean;
  error: string | null;
}

export interface SandboxRuntimeLog {
  id: string;
  level: "info" | "error";
  message: string;
  timestamp: number;
}

export function isSandboxWsOutbound(value: unknown): value is SandboxWsOutbound {
  if (!value || typeof value !== "object") {
    return false;
  }
  const payload = value as Partial<SandboxWsOutbound>;
  return typeof payload.message === "string" && typeof payload.session_id === "string";
}

export function isSandboxChatResponse(value: unknown): value is SandboxChatResponse {
  if (!value || typeof value !== "object") {
    return false;
  }
  const payload = value as Partial<SandboxChatResponse>;
  return (
    typeof payload.message === "string" &&
    typeof payload.session_id === "string" &&
    typeof payload.trace === "object" &&
    payload.trace !== null
  );
}

export function createEmptyTrace(): ExecutionTrace {
  return {
    nodes_triggered: [],
    transitions: [],
    rag_context: [],
    llm_metrics: null,
    errors: [],
    simulation: true,
    current_node_id: null,
  };
}

export function normalizeExecutionTrace(trace: Partial<ExecutionTrace> | null | undefined): ExecutionTrace {
  const base = createEmptyTrace();
  if (!trace) {
    return base;
  }
  return {
    nodes_triggered: Array.isArray(trace.nodes_triggered) ? trace.nodes_triggered : [],
    transitions: Array.isArray(trace.transitions) ? trace.transitions : [],
    rag_context: Array.isArray(trace.rag_context) ? trace.rag_context : [],
    llm_metrics: trace.llm_metrics ?? null,
    errors: Array.isArray(trace.errors) ? trace.errors : [],
    simulation: trace.simulation ?? true,
    current_node_id: trace.current_node_id ?? null,
  };
}

export function formatSimilarityScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function formatKztCost(value: number): string {
  return new Intl.NumberFormat("ru-KZ", {
    style: "currency",
    currency: "KZT",
    maximumFractionDigits: 2,
  }).format(value);
}

export function createSandboxMessage(
  role: SandboxChatMessage["role"],
  text: string,
  options?: { pending?: boolean },
): SandboxChatMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    timestamp: Date.now(),
    pending: options?.pending,
  };
}

export function summarizeTraceForConsole(trace: ExecutionTrace): string {
  const nodeCount = trace.nodes_triggered.length;
  const transitionCount = trace.transitions.length;
  const ragCount = trace.rag_context.length;
  const current = trace.current_node_id ?? "—";
  const topScore =
    ragCount > 0
      ? Math.max(...trace.rag_context.map((chunk) => chunk.similarity_score))
      : null;
  const scoreLabel = topScore == null ? "n/a" : formatSimilarityScore(topScore);
  return `node=${current} · steps=${nodeCount} · transitions=${transitionCount} · rag=${ragCount} (top ${scoreLabel})`;
}
