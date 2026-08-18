export interface OrganizationApiKeyProviderStatus {
  provider: string;
  label: string;
  configured: boolean;
  is_active: boolean;
  masked_key: string | null;
  updated_at: string | null;
}

export interface OrganizationApiKeyListResponse {
  items: OrganizationApiKeyProviderStatus[];
}

export interface OrganizationApiKeyUpsertRequest {
  provider: string;
  api_key: string;
  is_active?: boolean;
}

export interface OrganizationApiKeyUpsertResponse {
  provider: string;
  configured: boolean;
  masked_key: string | null;
  is_active: boolean;
  message: string;
}

export const LLM_API_KEY_PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "gemini", label: "Google Gemini" },
] as const;
