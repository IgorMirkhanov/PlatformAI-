export interface AdminUserSearchItem {
  id: string;
  email: string;
  full_name: string;
  organization_id: string;
  organization_name: string;
  plan_name: string;
  credit_balance: number;
  credit_balance_units: number;
  active_bots: number;
  last_activity_at: string | null;
  is_active: boolean;
  is_superadmin?: boolean;
  is_support?: boolean;
  platform_role?: "SUPERADMIN" | "SUPPORT" | "USER" | string;
}

export interface AdminUserSearchResponse {
  items: AdminUserSearchItem[];
  total: number;
  query: string;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface AdminClientItem {
  id: string;
  email: string;
  full_name: string;
  company_name: string;
  company_id: string;
  role: "OWNER" | "ADMIN" | "PROMPT_ENGINEER" | "OPERATOR";
  platform_role?: "SUPERADMIN" | "SUPPORT" | "ADMIN" | "USER" | string;
  is_superadmin: boolean;
  is_support?: boolean;
  is_active?: boolean;
  wallet_balance?: number;
  created_at: string;
}

export type AdminStripeStatus =
  | "none"
  | "active"
  | "past_due"
  | "canceled"
  | "trialing"
  | "expired"
  | string;

/** DTO for GET /api/v1/admin/organizations */
export interface AdminOrganizationItem {
  id: string;
  name: string;
  slug: string | null;
  owner_user_id: string;
  owner_email: string;
  wallet_balance: number;
  currency: "KZT" | "USD" | string;
  stripe_status: AdminStripeStatus;
  stripe_plan: string | null;
  active_bots: number;
  is_suspended: boolean;
  total_llm_spent: number;
  created_at: string;
}

export interface AdminOrganizationListResponse {
  organizations: AdminOrganizationItem[];
  total: number;
}

export interface AdminBalanceAdjustRequest {
  amount_delta: number;
  reason: string;
}

export interface AdminBalanceAdjustResponse {
  organization_id: string;
  organization_name: string;
  owner_user_id: string;
  previous_balance: number;
  amount_delta: number;
  new_balance: number;
  currency: string;
  transaction_id: string;
  message: string;
}

export type AdminTransactionStatus = "succeeded" | "pending" | "failed" | string;

export interface AdminTransactionItem {
  id: string;
  organization_id: string | null;
  organization_name: string | null;
  user_id: string;
  user_email: string;
  amount: number;
  currency: string;
  status: AdminTransactionStatus;
  status_raw: string;
  transaction_type: string;
  description: string;
  created_at: string;
}

export interface AdminTransactionListResponse {
  transactions: AdminTransactionItem[];
  total: number;
}

export type AdminLogLevel = "ERROR" | "WARNING" | "INFO" | string;

export interface AdminLogItem {
  id: string;
  level: AdminLogLevel;
  action: string;
  message: string;
  created_at: string;
  bot_id?: string | null;
}

export interface AdminLogListResponse {
  logs: AdminLogItem[];
  total: number;
}

export interface AdminStatsResponse {
  total_organizations: number;
  total_active_bots: number;
  total_revenue: number;
  total_llm_cost: number;
  total_tokens?: number;
  error_log_count?: number;
  currency: string;
}

export interface AdminOrganizationSuspendResponse {
  organization_id: string;
  organization_name: string;
  is_suspended: boolean;
  message: string;
}

export interface AdminBotItem {
  id: string;
  name: string;
  organization_id: string | null;
  organization_name: string | null;
  owner_email: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AdminBotListResponse {
  items?: AdminBotItem[];
  bots: AdminBotItem[];
  total: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface AdminAuditItem {
  id: string;
  admin_id: string;
  admin_email?: string | null;
  target_user_id: string;
  target_email?: string | null;
  organization_id: string | null;
  action: string;
  details: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface AdminAuditListResponse {
  items?: AdminAuditItem[];
  entries: AdminAuditItem[];
  total: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface AdminClientListResponse {
  items?: AdminClientItem[];
  clients: AdminClientItem[];
  total: number;
  query?: string;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface AdminUsageLogItem {
  id: string;
  org_id: string;
  organization_name?: string | null;
  bot_id?: string | null;
  bot_name?: string | null;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  created_at: string;
}

export interface AdminUsageLogListResponse {
  items: AdminUsageLogItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type AdminHealthStatus = "ok" | "degraded" | "error";
export type AdminPlatformState = "healthy" | "degraded" | "down";

export interface AdminHealthComponent {
  name: string;
  status: AdminHealthStatus;
  latency_ms?: number | null;
  detail?: string | null;
  meta?: Record<string, unknown>;
}

export interface AdminSystemHealthResponse {
  status: AdminPlatformState;
  checked_at: string;
  components: AdminHealthComponent[];
}

export interface ImpersonationResponse {
  access_token: string;
  token_type: string;
  organization_id: string;
  organization_name: string;
  impersonated_user_id: string;
  impersonated_user_email: string;
  impersonated_user_name: string;
  impersonated_user_role: string;
  impersonated_by: string;
  expires_at: string;
  headers: Record<string, string>;
  message: string;
}

export interface ImpersonationEndResponse {
  success: boolean;
  message: string;
}
