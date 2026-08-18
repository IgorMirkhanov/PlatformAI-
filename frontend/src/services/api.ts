import { apiRequest } from "@/lib/api";
import type {
  LlmModelListResponse,
  LlmModelTestConnectionRequest,
  LlmModelTestConnectionResponse,
} from "@/types/llm-model-api";

export async function getAvailableLlmModels(params?: {
  provider?: string;
  activeOnly?: boolean;
}): Promise<LlmModelListResponse> {
  const search = new URLSearchParams();
  if (params?.provider) {
    search.set("provider", params.provider);
  }
  if (params?.activeOnly === false) {
    search.set("active_only", "false");
  }
  const query = search.toString();
  const path = query ? `/api/v1/llm-models?${query}` : "/api/v1/llm-models";
  return apiRequest<LlmModelListResponse>(path);
}

export async function testLlmModelConnection(
  payload: LlmModelTestConnectionRequest,
): Promise<LlmModelTestConnectionResponse> {
  return apiRequest<LlmModelTestConnectionResponse>("/api/v1/llm-models/test-connection", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
