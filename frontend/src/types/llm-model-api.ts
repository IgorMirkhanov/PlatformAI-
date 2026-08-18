export interface LlmModelRecord {
  id: string;
  provider: string;
  model_name: string;
  display_name: string;
  base_url: string | null;
  context_window: number;
  cost_per_1k_input: string;
  cost_per_1k_output: string;
  is_active: boolean;
  is_system_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface LlmModelListResponse {
  items: LlmModelRecord[];
  total: number;
}

export interface LlmModelTestConnectionRequest {
  provider: string;
  model_name: string;
  base_url?: string | null;
  api_key?: string | null;
  model_id?: string | null;
}

export interface LlmModelTestConnectionResponse {
  ok: boolean;
  latency_ms: number;
  model: string;
  provider: string;
  message: string;
  sample_reply?: string | null;
}

export interface LlmModelCreatePayload {
  provider: string;
  model_name: string;
  display_name: string;
  base_url?: string | null;
  context_window?: number;
  cost_per_1k_input?: number | string;
  cost_per_1k_output?: number | string;
  is_active?: boolean;
  is_system_default?: boolean;
}

export interface LlmModelUpdatePayload {
  provider?: string;
  model_name?: string;
  display_name?: string;
  base_url?: string | null;
  context_window?: number;
  cost_per_1k_input?: number | string;
  cost_per_1k_output?: number | string;
  is_active?: boolean;
  is_system_default?: boolean;
}
