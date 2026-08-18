/** Multi-vendor LLM catalog — mirrors backend ``LLM_CREDIT_PRICING`` / ``MODEL_PROVIDER_MAP``. */

export interface LLMRegistryOption {
  id: string;
  label: string;
  provider: string;
  providerLabel: string;
}

export const DEFAULT_LLM_MODEL = "gpt-4o-mini";

export const LLM_REGISTRY_OPTIONS: LLMRegistryOption[] = [
  // OpenAI
  { id: "gpt-5.5", label: "GPT-5.5", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-5.4", label: "GPT-5.4", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-5.4-mini", label: "GPT-5.4 Mini", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-5.4-nano", label: "GPT-5.4 Nano", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-5", label: "GPT-5", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-4.1", label: "GPT-4.1", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-4o", label: "GPT-4o", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-4o-mini", label: "GPT-4o Mini", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-4-turbo", label: "GPT-4 Turbo", provider: "openai", providerLabel: "OpenAI" },
  { id: "gpt-3.5-turbo", label: "GPT-3.5 Turbo", provider: "openai", providerLabel: "OpenAI" },
  { id: "o4-mini", label: "o4-mini", provider: "openai", providerLabel: "OpenAI" },
  { id: "o3", label: "o3", provider: "openai", providerLabel: "OpenAI" },
  { id: "o3-mini", label: "o3-mini", provider: "openai", providerLabel: "OpenAI" },
  // Anthropic
  { id: "claude-4.7-opus", label: "Claude 4.7 Opus", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-4.6-opus", label: "Claude 4.6 Opus", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-4.6-sonnet", label: "Claude 4.6 Sonnet", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-4.5-sonnet", label: "Claude 4.5 Sonnet", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-4.5-haiku", label: "Claude 4.5 Haiku", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-4.1-opus", label: "Claude 4.1 Opus", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-3.5-sonnet", label: "Claude 3.5 Sonnet", provider: "anthropic", providerLabel: "Anthropic" },
  { id: "claude-3-haiku", label: "Claude 3 Haiku", provider: "anthropic", providerLabel: "Anthropic" },
  // Google Gemini
  { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash Lite", provider: "gemini", providerLabel: "Google Gemini" },
  { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash", provider: "gemini", providerLabel: "Google Gemini" },
  { id: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite", provider: "gemini", providerLabel: "Google Gemini" },
  // DeepSeek
  { id: "deepseek-chat", label: "DeepSeek Chat", provider: "deepseek", providerLabel: "DeepSeek" },
  { id: "deepseek-reasoner", label: "DeepSeek Reasoner", provider: "deepseek", providerLabel: "DeepSeek" },
  // GLM
  { id: "glm-5.1", label: "GLM 5.1", provider: "glm", providerLabel: "GLM (Zhipu)" },
  { id: "glm-5", label: "GLM 5", provider: "glm", providerLabel: "GLM (Zhipu)" },
  { id: "glm-5-turbo", label: "GLM 5 Turbo", provider: "glm", providerLabel: "GLM (Zhipu)" },
  // Qwen
  { id: "qwen-3.7-plus", label: "Qwen 3.7 Plus", provider: "qwen", providerLabel: "Qwen" },
  { id: "qwen-3.7-max", label: "Qwen 3.7 Max", provider: "qwen", providerLabel: "Qwen" },
];

export const LLM_REGISTRY_BY_PROVIDER = LLM_REGISTRY_OPTIONS.reduce<
  Record<string, LLMRegistryOption[]>
>((groups, option) => {
  const bucket = groups[option.providerLabel] ?? [];
  bucket.push(option);
  groups[option.providerLabel] = bucket;
  return groups;
}, {});

export function resolveRegistryModel(modelName: string | undefined | null): LLMRegistryOption {
  const normalized = (modelName || "").trim().toLowerCase();
  return (
    LLM_REGISTRY_OPTIONS.find((option) => option.id === normalized) ??
    LLM_REGISTRY_OPTIONS.find((option) => option.id === DEFAULT_LLM_MODEL)!
  );
}
