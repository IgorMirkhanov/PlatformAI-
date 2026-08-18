import type { PlatformType } from "@/types/bot";
import type { SubscriptionPlanName } from "@/types/billing";

export interface AgentStatusSummary {
  bot_id: string;
  bot_name: string;
  platform_type: PlatformType;
  is_active: boolean;
  channel_connected: boolean;
  flow_published: boolean;
  unique_dialogs: number;
  connected_channels: string[];
}

export interface DashboardStatsResponse {
  total_unique_dialogs: number;
  total_messages_dispatched: number;
  api_token_expenditure: number;
  active_agents: number;
  inactive_agents: number;
  subscription_balance: number;
  subscription_plan: SubscriptionPlanName;
  agents: AgentStatusSummary[];
  period_label: string;
}

export interface DailyChartPoint {
  label: string;
  messages: number;
  dialogs: number;
}

export type DiagnosticErrorType =
  | "LLM_TIMEOUT"
  | "RAG_EMPTY"
  | "CRM_DISCONNECT"
  | "INSUFFICIENT_FUNDS"
  | "GOOGLE_SYNC_FAILED"
  | "MESSENGER_API_ERROR";

export interface DiagnosticLogRead {
  id: string;
  bot_id: string;
  bot_name: string;
  client_id: string | null;
  error_type: DiagnosticErrorType;
  error_message: string;
  node_id: string | null;
  created_at: string;
}

export interface DiagnosticLogListResponse {
  logs: DiagnosticLogRead[];
  total: number;
}

export interface DiagnosticsExportResponse {
  markdown: string;
  bot_id: string | null;
  bot_name: string | null;
  error_count: number;
  generated_at: string;
}
