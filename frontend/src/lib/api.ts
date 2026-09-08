import type {
  BotAgentProfile,
  BotFunctionsUpdate,
  BotLLMConfigUpdate,
  BotPromptingUpdate,
  BotSettingsUpdate,
  OptimizePromptRequest,
  OptimizePromptResponse,
} from "@/types/agent";
import type { EnhancePromptRequest, EnhancePromptResponse } from "@/types/prompting";
import type { OptimizeAIPromptRequest, OptimizeAIPromptResponse } from "@/types/ai-prompts";
import type {
  OrganizationApiKeyListResponse,
  OrganizationApiKeyUpsertRequest,
  OrganizationApiKeyUpsertResponse,
} from "@/types/organization-api-keys";
import type {
  BalanceTopUpRequest,
  BillingStatusResponse,
  BillingTransactionListResponse,
  CardTopupRequest,
  CardTopupResponse,
  SavedTipTopPaymentMethod,
  DepositRequestPayload,
  DepositRequestResponse,
  SubscribeRequest,
  SubscribeResponse,
  SystemNotificationListResponse,
} from "@/types/billing";
import type {
  AmoCRMConnectRequest,
  Bitrix24ConnectRequest,
  CRMConnectResponse,
  CRMIntegrationPatchRequest,
  CRMIntegrationStatusResponse,
  CRMPipelineListResponse,
  CRMPlatform,
} from "@/types/crm";
import type {
  BotChannelsResponse,
  ChannelIntegrationType,
  ChannelStatus,
  PatchChannelRequest,
} from "@/types/channels";
import type {
  ChannelConnectRequest,
  ChannelConnectResponse,
  ChannelDisconnectResponse,
  HubChannelType,
  HubChannelsResponse,
} from "@/types/channel-hub";
import type { BotHealthTelemetry, PlatformType } from "@/types/bot";
import type { DashboardStatsResponse, DiagnosticLogListResponse, DiagnosticsExportResponse } from "@/types/dashboard";
import type { ExportedGraphJSON } from "@/types/flow";
import type {
  GoogleSyncAcceptedResponse,
  KnowledgeBaseDeleteResponse,
  KnowledgeBaseDocumentContextResponse,
  KnowledgeBaseDocumentContextUpdate,
  KnowledgeBaseDocumentListResponse,
  KnowledgeBaseTextUploadRequest,
  KnowledgeBaseUploadResponse,
} from "@/types/knowledge-base";
import type {
  KnowledgeAssetListResponse,
  KnowledgeChunksResponse,
  KnowledgeDeleteResponse,
  KnowledgeReindexRequest,
  KnowledgeReindexResponse,
  KnowledgeToggleRequest,
  KnowledgeToggleResponse,
  KnowledgeUploadResponse,
} from "@/types/knowledge";
import type {
  AcceptTeamInviteRequest,
  CreateCompanyRequest,
  CreateCompanyResponse,
  CurrentUser,
  OrganizationsListResponse,
  SwitchCompanyRequest,
  SwitchCompanyResponse,
  TeamInviteRequest,
  TeamInviteResponse,
  TeamMembersResponse,
  UpdateCurrentUserRequest,
  UpdateTeamMemberRoleRequest,
} from "@/types/team";
import type {
  AdminAuditListResponse,
  AdminBalanceAdjustRequest,
  AdminBalanceAdjustResponse,
  AdminBotListResponse,
  AdminClientListResponse,
  AdminLogListResponse,
  AdminOrganizationListResponse,
  AdminOrganizationSuspendResponse,
  AdminStatsResponse,
  AdminSystemHealthResponse,
  AdminTransactionListResponse,
  AdminUsageLogListResponse,
  AdminUserSearchResponse,
  ImpersonationEndResponse,
  ImpersonationResponse,
} from "@/types/admin";
import type {
  LlmModelCreatePayload,
  LlmModelListResponse,
  LlmModelRecord,
  LlmModelUpdatePayload,
} from "@/types/llm-model-api";
import type { SandboxChatResponse, SandboxClearResponse, SandboxMessageRequest } from "@/types/sandbox";
import { apiClientRequest } from "@/lib/api/client";
import { buildApiUrl, getApiBaseUrl } from "@/lib/api/baseUrl";
import { getAccessToken } from "@/lib/auth/tokens";
import { useBotStore } from "@/store/useBotStore";

export { buildApiUrl, getApiBaseUrl };

export interface ApiValidationIssue {
  code: string;
  message: string;
  node_id?: string | null;
  edge_id?: string | null;
  button_id?: string | null;
  field?: string | null;
}

export interface ApiValidationErrorBody {
  message?: string;
  issues?: ApiValidationIssue[];
  detail?: string | ApiValidationIssue[] | { msg: string; loc: string[] }[];
}

export interface ApiErrorBody {
  detail?:
    | string
    | ApiValidationErrorBody
    | Array<{ msg?: string; loc?: string[]; message?: string; field?: string }>;
  code?: string;
  fields?: Array<{ field?: string; message?: string }>;
  retry_after?: number;
  success?: boolean;
  error?: string;
  message?: string;
  correlation_id?: string;
  debug?: string;
}

export class ApiError extends Error {
  public issues: ApiValidationIssue[] = [];

  constructor(
    message: string,
    public status: number,
    issues: ApiValidationIssue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.issues = issues;
  }
}

export interface CreateBotRequest {
  name: string;
  platform_type?: PlatformType;
  user_id?: string;
  use_case?: "support_rag" | "sales_crm" | "empty";
}

export interface CreateBotResponse {
  bot_id: string;
  name: string;
  platform_type: PlatformType;
  is_active: boolean;
  message: string;
}

export interface BotAvatarUploadResponse {
  bot_id: string;
  avatar_url: string;
  message: string;
}

export interface SetupChannelRequest {
  channel_type?: ChannelIntegrationType;
  telegram_bot_token?: string;
  telegram_active?: boolean;
  whatsapp_phone_number_id?: string;
  whatsapp_business_account_id?: string;
  whatsapp_access_token?: string;
  whatsapp_verify_token?: string;
  instagram_page_id?: string;
  instagram_access_token?: string;
  vk_group_id?: string;
  vk_access_token?: string;
  web_widget_active?: boolean;
}

export interface SetupChannelResponse {
  bot_id: string;
  platform_type: PlatformType;
  channel_type?: ChannelIntegrationType | null;
  channel_connected: boolean;
  channel_active: boolean;
  webhook_url: string | null;
  token_hash: string | null;
  telegram_username?: string | null;
  verify_token?: string | null;
  embed_script?: string | null;
  message: string;
}

export type { BotChannelsResponse, ChannelStatus };

export interface TelegramSetupRequest {
  bot_token: string;
  bot_name?: string;
}

export interface TelegramSetupResponse {
  bot_id: string;
  bot_name: string;
  token_hash: string;
  webhook_url: string;
  telegram_username: string | null;
  message: string;
}

export interface PublishBotFlowRequest {
  title: string;
  graph_data: ExportedGraphJSON;
  is_published: boolean;
}

export interface PublishBotFlowResponse {
  bot_id: string;
  flow_id: string;
  title: string;
  is_published: boolean;
  node_count: number;
  edge_count: number;
  message: string;
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

export function getWsBaseUrl(): string {
  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}`;
  }

  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured?.startsWith("https://")) {
    return configured.replace("https://", "wss://").replace(/\/$/, "");
  }
  if (configured?.startsWith("http://")) {
    return configured.replace("http://", "ws://").replace(/\/$/, "");
  }

  const internal = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  if (internal.startsWith("https://")) {
    return internal.replace("https://", "wss://");
  }
  return internal.replace("http://", "ws://");
}

export function getOperatorWsUrl(operatorId: string, token?: string): string {
  const wsToken = token ?? getOperatorWsToken();
  return `${getWsBaseUrl()}/ws/operator/${operatorId}?token=${encodeURIComponent(wsToken)}`;
}

export function getOperatorWsToken(): string {
  return process.env.NEXT_PUBLIC_OPERATOR_WS_TOKEN ?? "dev-operator-token";
}

function extractValidationIssues(detail: ApiErrorBody["detail"], fields?: ApiErrorBody["fields"]): ApiValidationIssue[] {
  if (Array.isArray(fields) && fields.length > 0) {
    return fields.map((item) => ({
      code: "VALIDATION_ERROR",
      message: item.message || "Invalid value",
      field: item.field,
    }));
  }
  if (!detail || typeof detail === "string") {
    return [];
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => ({
      code: "validation_error",
      message: ("msg" in item && item.msg) || ("message" in item && item.message) || String(item),
      field: "field" in item ? item.field : undefined,
    }));
  }
  if ("issues" in detail && Array.isArray(detail.issues)) {
    return detail.issues;
  }
  return [];
}

function parseErrorMessage(body: ApiErrorBody, fallback: string): string {
  if (typeof body.error === "string" && body.error.trim()) {
    return body.error;
  }
  if (typeof body.message === "string" && body.message.trim() && body.success === false) {
    return body.message;
  }

  const fieldIssues = extractValidationIssues(body.detail, body.fields);
  if (body.code === "VALIDATION_ERROR" || (Array.isArray(body.fields) && body.fields.length > 0)) {
    if (fieldIssues.length > 0) {
      return fieldIssues
        .map((issue) => (issue.field ? `${issue.field}: ${issue.message}` : issue.message))
        .join("; ");
    }
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
  }

  if (body.code === "RATE_LIMIT_EXCEEDED" && typeof body.detail === "string") {
    return body.detail;
  }

  const detail = body.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const detailRecord = detail as { message?: string; code?: string; billing_url?: string };
    if (detailRecord.message) {
      const suffix =
        detailRecord.billing_url && detailRecord.code
          ? ` (${detailRecord.code})`
          : "";
      return `${detailRecord.message}${suffix}`;
    }
    const issues = extractValidationIssues(detail);
    if (issues.length > 0) {
      return issues.map((issue) => issue.message).join(" ");
    }
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => ("msg" in item && item.msg) || ("message" in item && item.message) || "")
      .filter(Boolean)
      .join(", ");
  }
  return fallback;
}

function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") {
    return {};
  }
  const { currentUser, activeCompanyId } = useBotStore.getState();
  const headers: Record<string, string> = {};

  // Prefer active Bearer (JWT or impersonation). Always attach when present.
  let hasBearer = false;
  try {
    const accessToken = getAccessToken();
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
      hasBearer = true;
    }
  } catch {
    // ignore storage access errors
  }

  // Soft-launch identity header only when no JWT is present (dev tooling).
  if (!hasBearer && currentUser?.id) {
    headers["X-User-Id"] = currentUser.id;
  }

  // Prefer bot-store active company (kept in sync with org store on switch).
  let orgId = activeCompanyId ?? currentUser?.company_id ?? null;
  try {
    const stored = window.localStorage.getItem("mpai_current_org_id");
    if (!orgId && stored) orgId = stored;
  } catch {
    // ignore
  }

  if (orgId) {
    headers["X-Company-Id"] = orgId;
    headers["X-Organization-Id"] = orgId;
  }
  return headers;
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  try {
    return await apiClientRequest<T>(path, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...getAuthHeaders(),
        ...options.headers,
      },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    const status =
      typeof error === "object" && error && "status" in error
        ? Number((error as { status?: number }).status) || 0
        : 0;
    const body =
      typeof error === "object" && error && "body" in error
        ? (error as { body?: ApiErrorBody }).body
        : undefined;
    const message = body
      ? parseErrorMessage(
          body,
          error instanceof Error
            ? error.message
            : `Request failed (${status || "network"})`,
        )
      : error instanceof Error
        ? error.message
        : `Request failed (${status || "network"})`;
    const issues = body ? extractValidationIssues(body.detail, body.fields) : [];
    throw new ApiError(message, status, issues);
  }
}

export async function fetchDashboardStats(userId?: string): Promise<DashboardStatsResponse> {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return apiRequest<DashboardStatsResponse>(`/api/v1/dashboard/stats${query}`);
}

export async function fetchDiagnosticLogs(
  userId?: string,
  limit = 25,
): Promise<DiagnosticLogListResponse> {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  params.set("limit", String(limit));
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<DiagnosticLogListResponse>(`/api/v1/dashboard/diagnostics${query}`);
}

export async function exportCursorDiagnostics(
  botId?: string,
  limit = 50,
): Promise<DiagnosticsExportResponse> {
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  params.set("limit", String(limit));
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<DiagnosticsExportResponse>(`/api/v1/system/diagnostics/export${query}`);
}

export function buildDashboardExportUrl(options?: {
  botId?: string;
  startDate?: string;
  endDate?: string;
  userId?: string;
}): string {
  const params = new URLSearchParams();
  if (options?.botId) params.set("bot_id", options.botId);
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);
  if (options?.userId) params.set("user_id", options.userId);
  const query = params.toString();
  return `/api/v1/dashboard/export${query ? `?${query}` : ""}`;
}

export function triggerDashboardExport(options?: {
  botId?: string;
  startDate?: string;
  endDate?: string;
  userId?: string;
}): void {
  const url = buildDashboardExportUrl(options);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "mp-ai-analytics.csv";
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

export async function fetchBillingStatus(userId?: string): Promise<BillingStatusResponse> {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return apiRequest<BillingStatusResponse>(`/api/v1/billing/status${query}`);
}

export async function fetchStripeStatus(organizationId?: string): Promise<{
  enabled: boolean;
  organization_id?: string;
  stripe_status?: string | null;
  plan?: string | null;
  has_customer?: boolean;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
}> {
  const query = organizationId
    ? `?organization_id=${encodeURIComponent(organizationId)}`
    : "";
  return apiRequest(`/api/v1/billing/stripe/status${query}`);
}

export async function createStripeCheckout(payload: {
  plan: "PRO" | "ENTERPRISE";
  success_url: string;
  cancel_url: string;
  organization_id?: string;
  price_id?: string;
}): Promise<{ id: string; url: string; organization_id?: string }> {
  return apiRequest("/api/v1/billing/stripe/checkout", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createStripePortal(
  returnUrl: string,
  organizationId?: string,
): Promise<{ url: string; organization_id?: string }> {
  return apiRequest("/api/v1/billing/stripe/portal", {
    method: "POST",
    body: JSON.stringify({
      return_url: returnUrl,
      organization_id: organizationId,
    }),
  });
}

/** Wallet / subscription Checkout — POST /api/v1/billing/checkout */
export async function createWalletCheckout(payload: {
  amount?: number;
  item_type?: "subscription" | "topup";
  plan_or_package_id?: string;
  provider?: string;
  success_url?: string;
  cancel_url?: string;
}): Promise<{
  checkout_url?: string;
  url?: string;
  id?: string;
  invoice_id?: string;
  amount?: number;
  amount_kzt?: number;
  currency?: string;
  tokens_allocated?: number;
}> {
  return apiRequest("/api/v1/billing/checkout", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchTopUpCatalog(): Promise<{
  packages: Array<{
    id: string;
    label: string;
    amount_usd: number;
    tokens_allocated: number;
  }>;
}> {
  return apiRequest("/api/v1/billing/catalog/topup");
}

export async function fetchSubscriptionCatalog(): Promise<{
  plans: Array<{
    id: string;
    label: string;
    amount_usd: number;
    tokens_allocated: number;
    plan_id: string;
  }>;
}> {
  return apiRequest("/api/v1/billing/catalog/subscriptions");
}

export async function fetchOrganizationWallet(): Promise<{
  organization_id: string;
  balance: number;
  currency: string;
}> {
  return apiRequest("/api/v1/billing/wallet");
}

export interface TokenWalletTransaction {
  id: string;
  tx_type: string;
  amount_tokens: number;
  balance_after: number;
  bot_id: string | null;
  model_used: string | null;
  created_at: string;
}

export interface TokenWalletOverview {
  organization_id: string;
  balance_tokens: number;
  credit_balance: number;
  status: string;
  low_balance_threshold: number;
  blocked_at: string | null;
  transactions: TokenWalletTransaction[];
}

export interface TokenUsageByBot {
  organization_id: string;
  days: number;
  items: Array<{ bot_id: string | null; amount_tokens: number }>;
}

export async function fetchTokenWallet(): Promise<TokenWalletOverview> {
  return apiRequest("/api/v1/wallet");
}

export async function fetchTokenUsageByBot(days = 7): Promise<TokenUsageByBot> {
  return apiRequest(`/api/v1/wallet/usage-by-bot?days=${days}`);
}

export interface VaultCredential {
  id: string;
  kind: string;
  label: string | null;
  status: string;
  last_error: string | null;
  last_validated_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchVaultCredentials(): Promise<{ items: VaultCredential[] }> {
  return apiRequest("/api/v1/credentials");
}

export async function createVaultCredential(body: {
  kind: string;
  payload: Record<string, string>;
  label?: string;
  validate_before_save?: boolean;
}): Promise<VaultCredential> {
  return apiRequest("/api/v1/credentials", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function revalidateVaultCredential(id: string): Promise<VaultCredential> {
  return apiRequest(`/api/v1/credentials/${encodeURIComponent(id)}/validate`, {
    method: "POST",
  });
}

export interface PlaygroundChatResponse {
  text: string;
  model_name: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_tokens: number;
  dry_run: boolean;
  wallet_blocked: boolean;
  rag_context: Array<{ text: string; similarity_score: number; file_name?: string | null }>;
}

export async function sendPlaygroundChat(body: {
  bot_id: string;
  message: string;
  dry_run?: boolean;
}): Promise<PlaygroundChatResponse> {
  return apiRequest("/api/v1/playground/chat", {
    method: "POST",
    body: JSON.stringify({ dry_run: true, ...body }),
  });
}

/** Customer Portal — GET /api/v1/billing/portal */
export async function openBillingPortal(): Promise<{ url: string }> {
  return apiRequest("/api/v1/billing/portal");
}

export async function fetchBillingUsage(
  days = 30,
  organizationId?: string,
): Promise<{
  period_days: number;
  since: string;
  organization_id?: string | null;
  metrics: Record<string, { quantity: number; cost: number }>;
}> {
  const params = new URLSearchParams({ days: String(days) });
  if (organizationId) params.set("organization_id", organizationId);
  return apiRequest(`/api/v1/billing/usage?${params.toString()}`);
}

export async function fetchOrgAnalytics(
  organizationId: string,
  days = 30,
): Promise<{
  organization_id: string;
  period_days: number;
  since: string;
  metrics: Record<string, { quantity: number; cost: number }>;
  message_count: number;
  estimated_cost: number;
}> {
  return apiRequest(
    `/api/v1/analytics/org/${encodeURIComponent(organizationId)}/summary?days=${days}`,
  );
}

export async function subscribeToPlan(payload: SubscribeRequest): Promise<SubscribeResponse> {
  return apiRequest<SubscribeResponse>("/api/v1/billing/subscribe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchBillingTransactions(
  options?: {
    userId?: string;
    limit?: number;
    offset?: number;
    typeGroup?: "topup" | "llm" | "all";
  },
): Promise<BillingTransactionListResponse> {
  const params = new URLSearchParams();
  if (options?.userId) params.set("user_id", options.userId);
  params.set("limit", String(options?.limit ?? 20));
  params.set("offset", String(options?.offset ?? 0));
  if (options?.typeGroup && options.typeGroup !== "all") {
    params.set("type_group", options.typeGroup);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<BillingTransactionListResponse>(`/api/v1/billing/transactions${query}`);
}

export async function topUpBalance(payload: BalanceTopUpRequest): Promise<SubscribeResponse["subscription"]> {
  return apiRequest<SubscribeResponse["subscription"]>("/api/v1/billing/top-up", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function submitDepositRequest(
  payload: DepositRequestPayload,
): Promise<DepositRequestResponse> {
  const formData = new FormData();
  formData.append("amount", String(payload.amount));
  formData.append("receipt", payload.receipt, payload.receipt.name);
  return apiRequest<DepositRequestResponse>("/api/v1/billing/deposit-request", {
    method: "POST",
    body: formData,
  });
}

/** Production wallet top-up via Stripe or TipTop Pay */
export async function topUpByCard(payload: CardTopupRequest): Promise<CardTopupResponse> {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return apiRequest<CardTopupResponse>("/api/v1/billing/topup", {
    method: "POST",
    body: JSON.stringify({
      amount: payload.amount,
      currency: payload.currency ?? "KZT",
      provider: payload.provider ?? "stripe",
      use_saved_card: payload.use_saved_card ?? false,
      tiptop_token: payload.tiptop_token,
      widget_mode: payload.widget_mode ?? false,
      success_url: payload.success_url ?? `${origin}/dashboard/billing?status=success`,
      cancel_url: payload.cancel_url ?? `${origin}/dashboard/billing?status=cancel`,
    }),
  });
}

/** Alias — wallet top-up by card */
export const topUpWallet = topUpByCard;

export async function fetchSavedTipTopPaymentMethod(): Promise<SavedTipTopPaymentMethod> {
  return apiRequest<SavedTipTopPaymentMethod>("/api/v1/billing/payment-methods/tiptop");
}

export async function fetchBillingNotifications(
  limit = 25,
): Promise<SystemNotificationListResponse> {
  return apiRequest<SystemNotificationListResponse>(
    `/api/v1/billing/notifications?limit=${limit}`,
  );
}

export async function fetchBotProfile(botId: string): Promise<BotAgentProfile> {
  return apiRequest<BotAgentProfile>(`/api/v1/bots/${botId}/profile`);
}

export async function updateBotSettings(
  botId: string,
  payload: BotSettingsUpdate,
): Promise<BotAgentProfile> {
  return apiRequest<BotAgentProfile>(`/api/v1/bots/${botId}/settings`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateBotPrompting(
  botId: string,
  payload: BotPromptingUpdate,
): Promise<BotAgentProfile> {
  return apiRequest<BotAgentProfile>(`/api/v1/bots/${botId}/prompting`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function enhanceBotPrompt(
  botId: string,
  payload: EnhancePromptRequest,
): Promise<EnhancePromptResponse> {
  return apiRequest<EnhancePromptResponse>(`/api/v1/bots/${botId}/prompting/enhance`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function optimizeBotPrompt(
  botId: string,
  payload: OptimizePromptRequest,
): Promise<OptimizePromptResponse> {
  return apiRequest<OptimizePromptResponse>(`/api/v1/bots/${botId}/prompting/optimize`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function optimizeAIPrompt(
  payload: OptimizeAIPromptRequest,
): Promise<OptimizeAIPromptResponse> {
  return apiRequest<OptimizeAIPromptResponse>("/api/v1/ai/optimize-prompt", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchOrganizationApiKeys(): Promise<OrganizationApiKeyListResponse> {
  return apiRequest<OrganizationApiKeyListResponse>("/api/v1/organizations/api-keys");
}

export async function upsertOrganizationApiKey(
  payload: OrganizationApiKeyUpsertRequest,
): Promise<OrganizationApiKeyUpsertResponse> {
  return apiRequest<OrganizationApiKeyUpsertResponse>("/api/v1/organizations/api-keys", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteOrganizationApiKey(provider: string): Promise<void> {
  await apiRequest<void>(`/api/v1/organizations/api-keys/${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
}

export {
  getAvailableLlmModels,
  testLlmModelConnection,
} from "@/services/api";

export async function updateBotLlmConfig(
  botId: string,
  payload: BotLLMConfigUpdate,
): Promise<BotAgentProfile> {
  return apiRequest<BotAgentProfile>(`/api/v1/bots/${botId}/llm-config`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateBotFunctions(
  botId: string,
  payload: BotFunctionsUpdate,
): Promise<BotAgentProfile> {
  return apiRequest<BotAgentProfile>(`/api/v1/bots/${botId}/functions`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function fetchAgentRagCollections(
  botId: string,
): Promise<{ bot_id: string; items: import("@/types/agent").AgentRagCollection[] }> {
  return apiRequest(`/api/v1/bots/${botId}/knowledge/agent-rag`);
}

export async function createAgentRagCollection(
  botId: string,
  payload: { function_name: string; description?: string; document_ids?: string[] },
): Promise<import("@/types/agent").AgentRagCollection> {
  return apiRequest(`/api/v1/bots/${botId}/knowledge/agent-rag`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAgentRagCollection(
  botId: string,
  ragId: string,
  payload: { function_name: string; description?: string; document_ids?: string[] },
): Promise<import("@/types/agent").AgentRagCollection> {
  return apiRequest(`/api/v1/bots/${botId}/knowledge/agent-rag/${ragId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteAgentRagCollection(botId: string, ragId: string): Promise<{ deleted: boolean }> {
  return apiRequest(`/api/v1/bots/${botId}/knowledge/agent-rag/${ragId}`, {
    method: "DELETE",
  });
}

export async function fetchCRMStatus(botId: string): Promise<CRMIntegrationStatusResponse> {
  return apiRequest<CRMIntegrationStatusResponse>(`/api/v1/bots/${botId}/crm/status`);
}

export async function fetchAppIntegrationsStatus(botId: string) {
  return apiRequest<{
    bot_id: string;
    platforms: Array<{
      platform: string;
      connected: boolean;
      sync_enabled: boolean;
      label: string;
      detail: string | null;
      webhook_url?: string | null;
      meta?: Record<string, unknown>;
    }>;
  }>(`/api/v1/bots/${botId}/app-integrations/status`);
}

export async function fetchGoogleCalendarAuthUrl(
  botId: string,
  purpose: "google" | "google_calendar" | "google_sheets" = "google",
): Promise<{ auth_url: string; state: string }> {
  const qs = purpose && purpose !== "google" ? `?purpose=${encodeURIComponent(purpose)}` : "";
  return apiRequest<{ auth_url: string; state: string }>(
    `/api/v1/bots/${botId}/integrations/google/auth-url${qs}`,
  );
}

export async function connectAppIntegration(
  botId: string,
  platform: string,
  payload: Record<string, unknown>,
) {
  return apiRequest<{
    bot_id: string;
    platform: string;
    connected: boolean;
    sync_enabled?: boolean;
    message: string;
    webhook_url?: string;
  }>(`/api/v1/bots/${botId}/app-integrations/${encodeURIComponent(platform)}/connect`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function disconnectAppIntegration(botId: string, platform: string) {
  return apiRequest<{ bot_id: string; platform: string; connected: boolean; message: string }>(
    `/api/v1/bots/${botId}/app-integrations/${encodeURIComponent(platform)}`,
    { method: "DELETE" },
  );
}

export async function patchAppIntegration(
  botId: string,
  platform: string,
  payload: Record<string, unknown>,
) {
  return apiRequest<{
    bot_id: string;
    platform: string;
    connected: boolean;
    sync_enabled?: boolean;
    message: string;
  }>(`/api/v1/bots/${botId}/app-integrations/${encodeURIComponent(platform)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function connectAmoCRM(
  botId: string,
  payload: AmoCRMConnectRequest,
): Promise<CRMConnectResponse> {
  return apiRequest<CRMConnectResponse>(`/api/v1/bots/${botId}/crm/amocrm/connect`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function connectBitrix24(
  botId: string,
  payload: Bitrix24ConnectRequest,
): Promise<CRMConnectResponse> {
  return apiRequest<CRMConnectResponse>(`/api/v1/bots/${botId}/crm/bitrix24/connect`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function patchCRMIntegration(
  botId: string,
  crmType: CRMPlatform,
  payload: CRMIntegrationPatchRequest,
): Promise<CRMConnectResponse> {
  return apiRequest<CRMConnectResponse>(
    `/api/v1/bots/${botId}/integrations/${encodeURIComponent(crmType)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchCRMPipelines(
  botId: string,
  platform: CRMPlatform,
): Promise<CRMPipelineListResponse> {
  return apiRequest<CRMPipelineListResponse>(
    `/api/v1/bots/${botId}/crm/pipelines?platform=${platform}`,
  );
}

export async function fetchKnowledgeBaseDocuments(
  botId: string,
): Promise<KnowledgeBaseDocumentListResponse> {
  return apiRequest<KnowledgeBaseDocumentListResponse>(
    `/api/v1/knowledge-base/${botId}/documents`,
  );
}

export async function updateKnowledgeDocumentContext(
  botId: string,
  documentId: string,
  payload: KnowledgeBaseDocumentContextUpdate,
): Promise<KnowledgeBaseDocumentContextResponse> {
  return apiRequest<KnowledgeBaseDocumentContextResponse>(
    `/api/v1/knowledge-base/${botId}/documents/${documentId}/context`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteKnowledgeBaseDocument(
  botId: string,
  documentId: string,
): Promise<KnowledgeBaseDeleteResponse> {
  return apiRequest<KnowledgeBaseDeleteResponse>(
    `/api/v1/knowledge-base/${botId}/documents/${documentId}`,
    { method: "DELETE" },
  );
}

export async function uploadKnowledgeBaseText(
  botId: string,
  payload: Omit<KnowledgeBaseTextUploadRequest, "knowledge_base_id">,
): Promise<KnowledgeBaseUploadResponse> {
  return apiRequest<KnowledgeBaseUploadResponse>("/api/v1/knowledge-base/upload", {
    method: "POST",
    body: JSON.stringify({
      knowledge_base_id: botId,
      text: payload.text,
      file_name: payload.file_name ?? "manual-entry.txt",
    }),
  });
}

export async function uploadKnowledgeBaseFile(
  botId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<KnowledgeBaseUploadResponse> {
  const formData = new FormData();
  formData.append("knowledge_base_id", botId);
  formData.append("file", file);
  onProgress?.(35);
  const result = await apiRequest<KnowledgeBaseUploadResponse>(
    "/api/v1/knowledge-base/upload/file",
    { method: "POST", body: formData },
  );
  onProgress?.(95);
  return result;
}

export async function fetchKnowledgeAssets(
  botId: string,
): Promise<KnowledgeAssetListResponse> {
  return apiRequest<KnowledgeAssetListResponse>(
    `/api/v1/bots/${botId}/knowledge/documents`,
  );
}

export async function fetchKnowledgeChunks(
  botId: string,
  documentId: string,
): Promise<KnowledgeChunksResponse> {
  return apiRequest<KnowledgeChunksResponse>(
    `/api/v1/bots/${botId}/knowledge/documents/${documentId}/chunks`,
  );
}

export async function uploadKnowledgeAsset(
  botId: string,
  payload: {
    file?: File;
    url?: string;
    text?: string;
    file_name?: string;
    crawl_depth?: number;
  },
  onProgress?: (percent: number) => void,
): Promise<KnowledgeUploadResponse> {
  const formData = new FormData();
  if (payload.file) {
    formData.append("file", payload.file);
  }
  if (payload.url?.trim()) {
    formData.append("url", payload.url.trim());
  }
  if (payload.text?.trim()) {
    formData.append("text", payload.text.trim());
  }
  if (payload.file_name?.trim()) {
    formData.append("file_name", payload.file_name.trim());
  }
  if (payload.crawl_depth !== undefined) {
    formData.append("crawl_depth", String(payload.crawl_depth));
  }

  onProgress?.(20);
  const result = await apiRequest<KnowledgeUploadResponse>(
    `/api/v1/bots/${botId}/knowledge/upload`,
    { method: "POST", body: formData },
  );
  onProgress?.(95);
  return result;
}

export async function toggleKnowledgeAsset(
  botId: string,
  payload: KnowledgeToggleRequest,
): Promise<KnowledgeToggleResponse> {
  return apiRequest<KnowledgeToggleResponse>(`/api/v1/bots/${botId}/knowledge/toggle`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteKnowledgeAsset(
  botId: string,
  documentId: string,
): Promise<KnowledgeDeleteResponse> {
  return apiRequest<KnowledgeDeleteResponse>(
    `/api/v1/bots/${botId}/knowledge/documents/${documentId}`,
    { method: "DELETE" },
  );
}

export interface KnowledgeTestSearchChunk {
  text: string;
  similarity_score: number;
  cosine_distance: number;
  match_percent: number;
  file_name?: string | null;
  document_id?: string | null;
  page_number?: number | null;
  section?: string | null;
  chunk_index?: number | null;
}

export interface KnowledgeTestSearchResponse {
  kb_id: string;
  query: string;
  top_k: number;
  chunks: KnowledgeTestSearchChunk[];
  total: number;
}

export interface KnowledgeAsyncUploadResponse {
  task_id: string;
  document_id: string;
  bot_id: string;
  kb_id: string;
  status: "PENDING" | "PARSING" | "INDEXED" | "FAILED";
  message?: string;
}

/** Stage-6 knowledge API — list documents for a kb (bot id). */
export async function fetchKnowledgeDocuments(
  kbId: string,
): Promise<KnowledgeAssetListResponse> {
  return apiRequest<KnowledgeAssetListResponse>(`/api/v1/knowledge/${kbId}/documents`);
}

export async function uploadKnowledgeDocumentAsync(
  kbId: string,
  payload: { file?: File; url?: string; file_name?: string; crawl_depth?: number },
): Promise<KnowledgeAsyncUploadResponse> {
  const formData = new FormData();
  if (payload.file) {
    formData.append("file", payload.file);
  }
  if (payload.url?.trim()) {
    formData.append("url", payload.url.trim());
  }
  if (payload.file_name?.trim()) {
    formData.append("file_name", payload.file_name.trim());
  }
  if (payload.crawl_depth !== undefined) {
    formData.append("crawl_depth", String(payload.crawl_depth));
  }

  return apiRequest<KnowledgeAsyncUploadResponse>(`/api/v1/knowledge/${kbId}/upload`, {
    method: "POST",
    body: formData,
  });
}

export async function deleteKnowledgeDocument(
  kbId: string,
  documentId: string,
): Promise<KnowledgeDeleteResponse> {
  return apiRequest<KnowledgeDeleteResponse>(
    `/api/v1/knowledge/${kbId}/documents/${documentId}`,
    { method: "DELETE" },
  );
}

export async function testKnowledgeSearch(
  kbId: string,
  payload: { query: string; top_k?: number },
): Promise<KnowledgeTestSearchResponse> {
  return apiRequest<KnowledgeTestSearchResponse>(`/api/v1/knowledge/${kbId}/test-search`, {
    method: "POST",
    body: JSON.stringify({
      query: payload.query,
      top_k: payload.top_k ?? 4,
    }),
  });
}

export async function reindexKnowledgeAsset(
  botId: string,
  documentId: string,
  payload: KnowledgeReindexRequest = {},
): Promise<KnowledgeReindexResponse> {
  return apiRequest<KnowledgeReindexResponse>(
    `/api/v1/bots/${botId}/knowledge/${documentId}/reindex`,
    {
      method: "POST",
      body: JSON.stringify({
        crawl_depth: payload.crawl_depth ?? 1,
      }),
    },
  );
}

export async function syncKnowledgeFromGoogle(
  botId: string,
  googleUrl: string,
): Promise<GoogleSyncAcceptedResponse> {
  return apiRequest<GoogleSyncAcceptedResponse>(`/api/v1/bots/${botId}/knowledge/google-sync`, {
    method: "POST",
    body: JSON.stringify({ google_url: googleUrl }),
  });
}

export async function createBot(payload: CreateBotRequest): Promise<CreateBotResponse> {
  return apiRequest<CreateBotResponse>("/api/v1/bots", {
    method: "POST",
    body: JSON.stringify({
      platform_type: "TELEGRAM",
      ...payload,
    }),
  });
}

export async function cloneBot(botId: string): Promise<CreateBotResponse> {
  return apiRequest<CreateBotResponse>(`/api/v1/bots/${encodeURIComponent(botId)}/clone`, {
    method: "POST",
  });
}

export async function deleteBot(botId: string): Promise<{
  bot_id: string;
  deleted: boolean;
  message?: string;
}> {
  return apiRequest(`/api/v1/bots/${encodeURIComponent(botId)}`, {
    method: "DELETE",
  });
}

export async function uploadBotAvatar(
  botId: string,
  file: File,
): Promise<BotAvatarUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<BotAvatarUploadResponse>(`/api/v1/bots/${botId}/avatar`, {
    method: "POST",
    body: formData,
  });
}

export async function fetchBotChannels(botId: string): Promise<BotChannelsResponse> {
  return apiRequest<BotChannelsResponse>(`/api/v1/bots/${botId}/channel-integrations`);
}

export async function fetchHubChannels(botId: string): Promise<HubChannelsResponse> {
  return apiRequest<HubChannelsResponse>(`/api/v1/bots/${botId}/channels`);
}

export async function connectHubChannel(
  botId: string,
  channelType: HubChannelType,
  payload: ChannelConnectRequest,
): Promise<ChannelConnectResponse> {
  return apiRequest<ChannelConnectResponse>(
    `/api/v1/bots/${botId}/channels/${encodeURIComponent(channelType)}/connect`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function disconnectHubChannel(
  botId: string,
  channelType: HubChannelType,
): Promise<ChannelDisconnectResponse> {
  return apiRequest<ChannelDisconnectResponse>(
    `/api/v1/bots/${botId}/channels/${encodeURIComponent(channelType)}/disconnect`,
    {
      method: "POST",
    },
  );
}

export async function patchHubChannelEnabled(
  botId: string,
  channelType: HubChannelType,
  enabled: boolean,
): Promise<{ success?: boolean; message: string; enabled: boolean }> {
  return apiRequest(`/api/v1/bots/${botId}/channels/${encodeURIComponent(channelType)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export function getWhatsAppQrWsUrl(botId: string): string {
  const base = `${getWsBaseUrl()}/api/v1/channels/${botId}/whatsapp/ws-qr`;
  const token = getAccessToken();
  if (!token) return base;
  return `${base}?token=${encodeURIComponent(token)}`;
}

export async function fetchWhatsAppSession(
  botId: string,
): Promise<import("@/types/channel-hub").WhatsAppSessionStatus> {
  return apiRequest(`/api/v1/whatsapp/${botId}/session`);
}

export async function startWhatsAppSession(botId: string): Promise<{ ok?: boolean; status?: string }> {
  return apiRequest(`/api/v1/whatsapp/${botId}/session/start`, { method: "POST" });
}

export async function refreshWhatsAppQr(botId: string): Promise<{ ok?: boolean; status?: string }> {
  return apiRequest(`/api/v1/whatsapp/${botId}/session/refresh-qr`, { method: "POST" });
}

export async function stopWhatsAppSession(botId: string): Promise<{ ok?: boolean; status?: string }> {
  return apiRequest(`/api/v1/whatsapp/${botId}/session/stop`, { method: "POST" });
}

export async function sendWhatsAppTestMessage(
  botId: string,
  payload: { to: string; text: string },
): Promise<{ ok: boolean; to: string; message: string }> {
  return apiRequest(`/api/v1/whatsapp/${botId}/test-message`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function setupChannelCredentials(
  botId: string,
  payload: SetupChannelRequest,
): Promise<SetupChannelResponse> {
  return apiRequest<SetupChannelResponse>(`/api/v1/bots/${botId}/setup-channel`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function patchBotChannel(
  botId: string,
  channelType: ChannelIntegrationType,
  payload: PatchChannelRequest,
): Promise<SetupChannelResponse> {
  return apiRequest<SetupChannelResponse>(
    `/api/v1/bots/${botId}/channels/${encodeURIComponent(channelType)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchBotFlow(botId: string): Promise<BotFlowResponse> {
  return apiRequest<BotFlowResponse>(`/api/v1/bots/${botId}/flow`);
}

export interface SaveBotFlowRequest {
  title?: string;
  nodes: ExportedGraphJSON["nodes"];
  edges: ExportedGraphJSON["edges"];
  is_published?: boolean;
}

export async function saveBotFlow(
  botId: string,
  payload: SaveBotFlowRequest,
): Promise<PublishBotFlowResponse> {
  return apiRequest<PublishBotFlowResponse>(`/api/v1/bots/${botId}/flow`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function publishBotFlow(
  botId: string,
  payload: PublishBotFlowRequest,
): Promise<PublishBotFlowResponse> {
  return apiRequest<PublishBotFlowResponse>(`/api/v1/bots/${botId}/publish`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchBotHealth(botId: string): Promise<BotHealthTelemetry> {
  return apiRequest<BotHealthTelemetry>(`/api/v1/health/bots/${botId}`);
}

export async function fetchAllBotsHealth(): Promise<{ bots: BotHealthTelemetry[]; total: number }> {
  return apiRequest<{ bots: BotHealthTelemetry[]; total: number }>("/api/v1/health/bots");
}

/** @deprecated Use createBot + setupChannelCredentials instead */
export async function setupTelegramBot(
  payload: TelegramSetupRequest,
): Promise<TelegramSetupResponse> {
  return apiRequest<TelegramSetupResponse>("/api/v1/bots/setup-telegram", {
    method: "POST",
    body: JSON.stringify({
      bot_token: payload.bot_token,
      bot_name: payload.bot_name ?? "Telegram Bot",
    }),
  });
}

import type {
  ActiveChatsResponse,
  ChatMessage,
  ClientInboxProfile,
  CreateCrmDealResponse,
  InterceptChatResponse,
  OperatorContext,
  ToggleOperatorResponse,
} from "@/types/inbox";

export async function fetchOperatorContext(): Promise<OperatorContext> {
  return apiRequest<OperatorContext>("/api/v1/chats/operators/context");
}

export async function fetchActiveChats(): Promise<ActiveChatsResponse> {
  return apiRequest<ActiveChatsResponse>("/api/v1/chats/active");
}

export async function fetchClientMessages(
  clientId: string,
): Promise<ChatMessage[]> {
  return apiRequest<ChatMessage[]>(`/api/v1/chats/${clientId}/messages`);
}

export async function sendManualMessage(
  clientId: string,
  messageText: string,
): Promise<ChatMessage> {
  return apiRequest<ChatMessage>(`/api/v1/chats/${clientId}/send-manual`, {
    method: "POST",
    body: JSON.stringify({ message_text: messageText }),
  });
}

export async function toggleOperatorControl(
  clientId: string,
  paused?: boolean,
): Promise<ToggleOperatorResponse> {
  const body = paused === undefined ? {} : { paused };
  return apiRequest<ToggleOperatorResponse>(
    `/api/v1/chats/${clientId}/toggle-operator`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function interceptChatSession(
  sessionId: string,
  action: "intercept" | "release" = "intercept",
): Promise<InterceptChatResponse> {
  if (action === "release") {
    return resumeChatSession(sessionId);
  }

  return apiRequest<InterceptChatResponse>(
    `/api/v1/chat/${sessionId}/intercept`,
    {
      method: "POST",
      body: JSON.stringify({ action: "intercept" }),
    },
  );
}

export async function resumeChatSession(
  sessionId: string,
): Promise<InterceptChatResponse> {
  return apiRequest<InterceptChatResponse>(
    `/api/v1/chat/${sessionId}/resume`,
    {
      method: "POST",
      body: JSON.stringify({}),
    },
  );
}

export async function fetchClientInboxProfile(
  sessionId: string,
): Promise<ClientInboxProfile> {
  return apiRequest<ClientInboxProfile>(`/api/v1/chat/${sessionId}/profile`);
}

export async function createInboxCrmDeal(
  sessionId: string,
): Promise<CreateCrmDealResponse> {
  return apiRequest<CreateCrmDealResponse>(
    `/api/v1/chat/${sessionId}/crm/create-deal`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/api/v1/team/me");
}

export async function fetchAdminClients(
  query = "",
  limit = 50,
): Promise<AdminClientListResponse> {
  return fetchAdminUsers({ search: query || undefined, page_size: limit, page: 1 });
}

export async function fetchAdminUsers(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
}): Promise<AdminClientListResponse> {
  const search = new URLSearchParams();
  search.set("page", String(params?.page ?? 1));
  search.set("page_size", String(params?.page_size ?? 20));
  if (params?.search) search.set("search", params.search);
  if (params?.status) search.set("status", params.status);
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  return apiRequest<AdminClientListResponse>(`/api/v1/admin/users?${search.toString()}`);
}

export async function updateAdminUserPlatformRole(
  userId: string,
  platformRole: "USER" | "ADMIN" | "SUPERADMIN",
): Promise<{
  id: string;
  email: string;
  platform_role: string;
  is_superadmin: boolean;
  is_support: boolean;
  message: string;
}> {
  return apiRequest(`/api/v1/admin/users/${userId}/platform-role`, {
    method: "PATCH",
    body: JSON.stringify({ platform_role: platformRole }),
  });
}

export async function fetchAdminBots(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  /** @deprecated use page_size */
  limit?: number;
} | number): Promise<AdminBotListResponse> {
  const normalized =
    typeof params === "number" ? { page: 1, page_size: params } : params ?? {};
  const search = new URLSearchParams();
  search.set("page", String(normalized.page ?? 1));
  search.set(
    "page_size",
    String(normalized.page_size ?? normalized.limit ?? 20),
  );
  if (normalized.search) search.set("search", normalized.search);
  if (normalized.status) search.set("status", normalized.status);
  if (normalized.date_from) search.set("date_from", normalized.date_from);
  if (normalized.date_to) search.set("date_to", normalized.date_to);
  return apiRequest<AdminBotListResponse>(`/api/v1/admin/bots?${search.toString()}`);
}

export async function fetchAdminAudit(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  action?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}): Promise<AdminAuditListResponse> {
  const search = new URLSearchParams();
  if (params?.limit != null && params.page == null) {
    search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
  } else {
    search.set("page", String(params?.page ?? 1));
    search.set("page_size", String(params?.page_size ?? params?.limit ?? 20));
  }
  if (params?.search) search.set("search", params.search);
  if (params?.action) search.set("action", params.action);
  if (params?.status) search.set("status", params.status);
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  return apiRequest<AdminAuditListResponse>(`/api/v1/admin/audit-logs?${search.toString()}`);
}

export async function fetchAdminUsageLogs(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  model?: string;
}): Promise<AdminUsageLogListResponse> {
  const search = new URLSearchParams();
  search.set("page", String(params?.page ?? 1));
  search.set("page_size", String(params?.page_size ?? 20));
  if (params?.search) search.set("search", params.search);
  if (params?.status) search.set("status", params.status);
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.model) search.set("model", params.model);
  return apiRequest<AdminUsageLogListResponse>(`/api/v1/admin/usage-logs?${search.toString()}`);
}

export async function fetchAdminSystemHealth(): Promise<AdminSystemHealthResponse> {
  return apiRequest<AdminSystemHealthResponse>("/api/v1/admin/system-health");
}

export async function fetchAdminOrganizations(): Promise<AdminOrganizationListResponse> {
  return apiRequest<AdminOrganizationListResponse>("/api/v1/admin/organizations");
}

export async function toggleAdminOrganizationSuspension(
  organizationId: string,
): Promise<AdminOrganizationSuspendResponse> {
  return apiRequest<AdminOrganizationSuspendResponse>(
    `/api/v1/admin/organizations/${encodeURIComponent(organizationId)}/suspend`,
    { method: "POST" },
  );
}

export async function adjustAdminOrganizationBalance(
  organizationId: string,
  payload: AdminBalanceAdjustRequest,
): Promise<AdminBalanceAdjustResponse> {
  return apiRequest<AdminBalanceAdjustResponse>(
    `/api/v1/admin/organizations/${encodeURIComponent(organizationId)}/balance`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function adjustAdminBotBalance(
  botId: string,
  payload: { amount_delta: number; reason: string },
): Promise<{
  bot_id: string;
  bot_name: string;
  previous_balance: number;
  new_balance: number;
  amount_delta: number;
  message: string;
}> {
  return apiRequest(`/api/v1/admin/bots/${encodeURIComponent(botId)}/balance`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function setAdminBotSubscription(
  botId: string,
  payload: { active: boolean; reason: string; expires_at?: string | null },
): Promise<{
  bot_id: string;
  bot_name: string;
  subscription_active: boolean;
  wallet_balance: number;
  message: string;
}> {
  return apiRequest(`/api/v1/admin/bots/${encodeURIComponent(botId)}/subscription`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchAdminTransactions(limit = 200): Promise<AdminTransactionListResponse> {
  return apiRequest<AdminTransactionListResponse>(
    `/api/v1/admin/transactions?limit=${limit}`,
  );
}

export async function fetchAdminLogs(limit = 100): Promise<AdminLogListResponse> {
  return apiRequest<AdminLogListResponse>(`/api/v1/admin/logs?limit=${limit}`);
}

export async function fetchAdminStats(): Promise<AdminStatsResponse> {
  return apiRequest<AdminStatsResponse>("/api/v1/admin/stats");
}

/**
 * List / search platform users. An empty `query` returns every registered
 * account (paginated) so the support table renders on first load.
 */
export async function fetchAdminUserSearch(
  query = "",
  options: { page?: number; pageSize?: number } = {},
): Promise<AdminUserSearchResponse> {
  const search = new URLSearchParams();
  search.set("q", query.trim());
  search.set("page", String(options.page ?? 1));
  search.set("page_size", String(options.pageSize ?? 25));
  return apiRequest<AdminUserSearchResponse>(
    `/api/v1/admin/users/search?${search.toString()}`,
  );
}

export async function fetchAdminLlmModels(): Promise<LlmModelListResponse> {
  return apiRequest<LlmModelListResponse>("/api/v1/admin/llm-models");
}

export async function createAdminLlmModel(
  payload: LlmModelCreatePayload,
): Promise<LlmModelRecord> {
  return apiRequest<LlmModelRecord>("/api/v1/admin/llm-models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminLlmModel(
  modelId: string,
  payload: LlmModelUpdatePayload,
): Promise<LlmModelRecord> {
  return apiRequest<LlmModelRecord>(
    `/api/v1/admin/llm-models/${encodeURIComponent(modelId)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteAdminLlmModel(modelId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/admin/llm-models/${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });
}

export async function impersonateClientByEmail(
  email: string,
  password: string,
): Promise<ImpersonationResponse> {
  return apiRequest<ImpersonationResponse>("/api/v1/admin/impersonate", {
    method: "POST",
    body: JSON.stringify({ user_email: email, password }),
  });
}

export async function impersonateClientByUserId(
  userId: string,
  password: string,
): Promise<ImpersonationResponse> {
  return apiRequest<ImpersonationResponse>(
    `/api/v1/admin/impersonate/user/${encodeURIComponent(userId)}`,
    {
      method: "POST",
      body: JSON.stringify({ password }),
    },
  );
}

export async function endImpersonationSession(payload?: {
  target_user_id?: string;
  email?: string;
}): Promise<ImpersonationEndResponse> {
  return apiRequest<ImpersonationEndResponse>("/api/v1/admin/impersonate/end", {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export async function updateCurrentUserProfile(
  payload: UpdateCurrentUserRequest,
): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/api/v1/team/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function fetchOrganizations(): Promise<OrganizationsListResponse> {
  return apiRequest<OrganizationsListResponse>("/api/v1/team/organizations");
}

export async function fetchOrganizationUsage(): Promise<import("@/types/organization").OrganizationUsage> {
  return apiRequest("/api/v1/organizations/usage");
}

export async function createCompanyWorkspace(
  payload: CreateCompanyRequest,
): Promise<CreateCompanyResponse> {
  return apiRequest<CreateCompanyResponse>("/api/v1/team/companies", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function switchCompanyWorkspace(
  payload: SwitchCompanyRequest,
): Promise<SwitchCompanyResponse> {
  return apiRequest<SwitchCompanyResponse>("/api/v1/team/switch-company", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchTeamMembers(): Promise<TeamMembersResponse> {
  return apiRequest<TeamMembersResponse>("/api/v1/team/members");
}

export async function inviteTeamMember(payload: TeamInviteRequest): Promise<TeamInviteResponse> {
  return apiRequest<TeamInviteResponse>("/api/v1/team/invite", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function acceptTeamInvite(payload: AcceptTeamInviteRequest): Promise<void> {
  await apiRequest("/api/v1/team/accept-invite", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateTeamMemberRole(
  memberId: string,
  payload: UpdateTeamMemberRoleRequest,
): Promise<TeamMembersResponse["members"][number]> {
  return apiRequest<TeamMembersResponse["members"][number]>(
    `/api/v1/team/members/${memberId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function revokeTeamMember(memberId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/team/members/${memberId}`, {
    method: "DELETE",
  });
}

export async function cancelTeamInvitation(invitationId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/team/invites/${invitationId}`, {
    method: "DELETE",
  });
}

export function getSandboxWsUrl(botId: string): string {
  const wsBase = getWsBaseUrl();
  const path = `/api/v1/sandbox/${encodeURIComponent(botId)}`;
  if (wsBase.endsWith("/api")) {
    return `${wsBase}/v1/sandbox/${encodeURIComponent(botId)}`;
  }
  return `${wsBase}${path}`;
}

/** Streaming execution channel: /api/v1/ws/execution/{sessionId} */
export function getExecutionWsUrl(sessionId: string): string {
  const wsBase = getWsBaseUrl();
  const path = `/api/v1/ws/execution/${encodeURIComponent(sessionId)}`;
  if (wsBase.endsWith("/api")) {
    return `${wsBase}/v1/ws/execution/${encodeURIComponent(sessionId)}`;
  }
  return `${wsBase}${path}`;
}

export async function executeBotFlow(
  botId: string,
  payload: { message: string; session_id?: string; use_draft?: boolean },
): Promise<{
  session_id: string;
  bot_id: string;
  reply_text: string;
  current_step_id: string;
  is_waiting: boolean;
  nodes_visited: string[];
  variables: Record<string, unknown>;
  error: string | null;
  handoff: boolean;
}> {
  return apiRequest(`/api/v1/bots/${encodeURIComponent(botId)}/execute`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function sendSandboxMessage(
  botId: string,
  payload: SandboxMessageRequest,
): Promise<SandboxChatResponse> {
  return apiRequest<SandboxChatResponse>(
    `/api/v1/sandbox/${encodeURIComponent(botId)}/message`,
    {
      method: "POST",
      body: JSON.stringify({
        text: payload.text,
        session_id: payload.session_id ?? null,
      }),
    },
  );
}

export async function clearSandboxSession(
  botId: string,
  sessionId?: string,
): Promise<SandboxClearResponse> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return apiRequest<SandboxClearResponse>(
    `/api/v1/sandbox/${encodeURIComponent(botId)}/clear${query}`,
    { method: "POST" },
  );
}
