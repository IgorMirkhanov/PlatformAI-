import type { PlatformType } from "@/types/bot";

export interface ScheduleWindow {
  day: string;
  start: string;
  end: string;
}

export type Weekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

export interface ScheduleConfig {
  enabled: boolean;
  timezone: string;
  windows: ScheduleWindow[];
  day_enabled?: Partial<Record<Weekday, boolean>>;
}

export interface DayScheduleUI {
  day: Weekday;
  enabled: boolean;
  intervals: Array<{ start: string; end: string }>;
}

export interface BotAgentProfile {
  id: string;
  user_id: string;
  name: string;
  platform_type: PlatformType;
  is_active: boolean;
  default_chat_state: boolean;
  timezone: string;
  schedule_config: ScheduleConfig;
  prompt_instructions: string;
  llm_model_name: string;
  llm_temperature: number;
  message_split: boolean;
  message_buffer_delay: number;
  custom_code_snippet: string;
  function_tools?: FunctionToolDefinition[];
  agent_rag?: AgentRagCollection[];
  openai_tools?: OpenAIToolSchema[];
  show_username_visibility: boolean;
  show_messenger_visibility: boolean;
  show_datetime_visibility: boolean;
  avatar_url?: string | null;
}

export interface BotSettingsUpdate {
  name?: string;
  is_active?: boolean;
  default_chat_state?: boolean;
  timezone?: string;
  schedule_config?: ScheduleConfig;
  message_split?: boolean;
  message_buffer_delay?: number;
}

export interface BotPromptingUpdate {
  prompt_instructions?: string;
  llm_model_name?: string;
  llm_temperature?: number;
  show_username_visibility?: boolean;
  show_messenger_visibility?: boolean;
  show_datetime_visibility?: boolean;
}

export interface OptimizePromptRequest {
  prompt_instructions: string;
}

export interface OptimizePromptResponse {
  bot_id: string;
  optimized_prompt: string;
  message: string;
}

export interface BotLLMConfigUpdate {
  llm_model_name: string;
  llm_temperature: number;
}

export interface BotFunctionsUpdate {
  custom_code_snippet?: string;
  function_tools?: FunctionToolDefinition[];
}

export type FunctionParamType = "string" | "number" | "boolean";

export interface FunctionToolParameter {
  name: string;
  type: FunctionParamType;
  instruction: string;
  required: boolean;
  enum_values?: string;
}

export interface FunctionResultField {
  id: string;
  name: string;
  action: "text" | "system";
  value: string;
}

export interface FunctionToolDefinition {
  id: string;
  name: string;
  description: string;
  parameters: FunctionToolParameter[];
  reaction_mode: "llm" | "fixed";
  reaction_text: string;
  integration: FunctionIntegrationKind;
  result_integrations?: FunctionIntegrationKind[];
  result_fields?: FunctionResultField[];
  post_scenario?: "continue" | "end";
  nested_function_id?: string | null;
  disable_delayed_messages?: boolean;
  is_active: boolean;
}

export type FunctionIntegrationKind =
  | "none"
  | "telegram"
  | "whatsapp"
  | "google_sheets"
  | "custom_api"
  | "file"
  | "python"
  | "tags"
  | "delayed";

export interface AgentRagCollection {
  id: string;
  function_name: string;
  description: string;
  document_ids: string[];
}

export interface OpenAIToolSchema {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export const FUNCTION_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export const FUNCTION_INTEGRATION_OPTIONS: Array<{
  id: FunctionIntegrationKind;
  label: string;
}> = [
  { id: "none", label: "Не отправлять" },
  { id: "telegram", label: "Telegram отчёт" },
  { id: "whatsapp", label: "WhatsApp-группа" },
  { id: "google_sheets", label: "Google Sheets" },
  { id: "custom_api", label: "Custom API" },
  { id: "file", label: "Отправка файла" },
  { id: "python", label: "Python" },
  { id: "tags", label: "Теги" },
  { id: "delayed", label: "Отложенные" },
];


export type AgentTabId =
  | "settings"
  | "prompting"
  | "messages"
  | "llm-models"
  | "control"
  | "functions"
  | "knowledge-base"
  | "integrations"
  | "channels"
  | "scenario";

export interface LLMModelOption {
  id: string;
  label: string;
  provider: string;
  costPer1kTokens: number;
  description: string;
}

export const LLM_MODEL_OPTIONS: LLMModelOption[] = [
  {
    id: "gpt-4o-mini",
    label: "GPT-4o Mini",
    provider: "OpenAI",
    costPer1kTokens: 0.002,
    description: "Fast, cost-efficient general assistant",
  },
  {
    id: "gpt-4o",
    label: "GPT-4o",
    provider: "OpenAI",
    costPer1kTokens: 0.015,
    description: "Highest quality reasoning and tool use",
  },
  {
    id: "llama3",
    label: "Llama 3",
    provider: "Ollama",
    costPer1kTokens: 0.0,
    description: "Self-hosted open-weight model",
  },
  {
    id: "claude-3.5-sonnet",
    label: "Claude 3.5 Sonnet",
    provider: "Anthropic",
    costPer1kTokens: 0.012,
    description: "Strong long-context performance",
  },
];

export const AVATAR_PRESETS = ["🤖", "✨", "💬", "🚀", "🎯", "⚡"] as const;

export const TIMEZONE_OPTIONS = [
  "Asia/Almaty",
  "Asia/Tashkent",
  "Europe/Moscow",
  "UTC",
  "America/New_York",
  "Europe/London",
] as const;

export const WEEKDAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

export const TIMEZONE_LABELS: Record<(typeof TIMEZONE_OPTIONS)[number], string> = {
  "Asia/Almaty": "Asia/Almaty (GMT+5)",
  "Asia/Tashkent": "Asia/Tashkent (GMT+5)",
  "Europe/Moscow": "Europe/Moscow (GMT+3)",
  UTC: "UTC (GMT+0)",
  "America/New_York": "America/New_York (GMT-5)",
  "Europe/London": "Europe/London (GMT+0)",
};

export const WEEKDAY_LABELS: Record<(typeof WEEKDAYS)[number], string> = {
  monday: "Пн",
  tuesday: "Вт",
  wednesday: "Ср",
  thursday: "Чт",
  friday: "Пт",
  saturday: "Сб",
  sunday: "Вс",
};

export const DEFAULT_SCHEDULE_WINDOWS: ScheduleWindow[] = [
  { day: "monday", start: "00:00", end: "23:59" },
  { day: "tuesday", start: "00:00", end: "23:59" },
  { day: "wednesday", start: "00:00", end: "23:59" },
  { day: "thursday", start: "00:00", end: "23:59" },
  { day: "friday", start: "00:00", end: "23:59" },
  { day: "saturday", start: "00:00", end: "23:59" },
  { day: "sunday", start: "00:00", end: "23:59" },
];

export const DEFAULT_DAY_INTERVAL = { start: "00:00", end: "23:59" } as const;
