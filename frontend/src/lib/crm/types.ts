/** Native CRM domain types (Phase A) — mirrors backend `/api/v1/crm/*` schemas. */

export type CrmDealStatus = "open" | "won" | "lost";

export interface CrmStage {
  id: string;
  organization_id: string;
  pipeline_id: string;
  name: string;
  position: number;
  color: string | null;
  is_won: boolean;
  is_lost: boolean;
  created_at: string;
  updated_at: string;
}

export interface CrmPipeline {
  id: string;
  organization_id: string;
  name: string;
  position: number;
  is_default: boolean;
  stages: CrmStage[];
  created_at: string;
  updated_at: string;
}

export interface CrmContactBrief {
  id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  source?: string | null;
  linked_client_id?: string | null;
}

export interface CrmContact {
  id: string;
  organization_id: string;
  account_id: string | null;
  first_name: string;
  last_name: string;
  phone: string | null;
  email: string | null;
  source: string | null;
  linked_client_id: string | null;
  custom_fields: Record<string, unknown>;
  avatar_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmContactListResponse {
  items: CrmContact[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmDealStageBrief {
  id: string;
  name: string;
  position: number;
  is_won: boolean;
  is_lost: boolean;
}

export interface CrmDeal {
  id: string;
  organization_id: string;
  pipeline_id: string;
  stage_id: string;
  contact_id: string | null;
  account_id: string | null;
  bot_id: string | null;
  assigned_user_id: string | null;
  title: string;
  amount: string | number;
  currency: string;
  status: CrmDealStatus;
  source: string | null;
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  stage?: CrmDealStageBrief | null;
  contact?: CrmContactBrief | null;
}

export interface CrmDealListResponse {
  items: CrmDeal[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmNote {
  id: string;
  organization_id: string;
  deal_id: string | null;
  contact_id: string | null;
  author_id: string | null;
  text: string;
  created_at: string;
  updated_at: string;
}

export interface CrmNoteListResponse {
  items: CrmNote[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmTimelineEvent {
  id: string;
  organization_id: string;
  deal_id: string | null;
  contact_id: string | null;
  actor_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface CrmTimelineListResponse {
  items: CrmTimelineEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmMoveStageRequest {
  stage_id: string;
}

/** Aliases matching the Step 7 prompt naming. */
export type Pipeline = CrmPipeline;
export type Stage = CrmStage;
export type Deal = CrmDeal;
export type Contact = CrmContact;

/** Phase C — analytics transport types */
export interface CrmFunnelStageStat {
  stage_id: string;
  stage_name: string;
  position: number;
  deal_count: number;
  amount_sum: string | number;
}

export interface CrmFunnelResponse {
  pipeline_id: string;
  stages: CrmFunnelStageStat[];
  total_deals: number;
  won_deals: number;
  conversion_rate: number;
}

export interface CrmManagerPerformanceRow {
  assigned_user_id: string | null;
  won_count: number;
  lost_count: number;
  revenue: string | number;
}

export interface CrmPerformanceResponse {
  items: CrmManagerPerformanceRow[];
}

export interface CrmForecastResponse {
  open_deal_count: number;
  forecast_amount: string | number;
}

/** Automation rules */
export type CrmAutomationTriggerType =
  | "stage_entered"
  | "field_changed"
  | "tag_added"
  | "no_activity_for"
  | "deal_created";

export interface CrmAutomationRule {
  id: string;
  organization_id: string;
  name: string;
  is_active: boolean;
  trigger_type: CrmAutomationTriggerType;
  trigger_config: Record<string, unknown>;
  conditions: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface CrmAutomationRuleListResponse {
  items: CrmAutomationRule[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmAutomationRuleCreate {
  name: string;
  is_active?: boolean;
  trigger_type: CrmAutomationTriggerType;
  trigger_config?: Record<string, unknown>;
  conditions?: Record<string, unknown>;
  actions?: Array<Record<string, unknown>>;
}

export interface CrmAutomationRuleUpdate {
  name?: string;
  is_active?: boolean;
  trigger_type?: CrmAutomationTriggerType;
  trigger_config?: Record<string, unknown>;
  conditions?: Record<string, unknown>;
  actions?: Array<Record<string, unknown>>;
}

/** Outbound webhook subscriptions */
export type CrmWebhookEventType =
  | "*"
  | "deal.created"
  | "deal.updated"
  | "deal.closed"
  | "contact.created";

export interface CrmWebhookSubscription {
  id: string;
  organization_id: string;
  target_url: string;
  event_types: string[];
  secret: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CrmWebhookSubscriptionListResponse {
  items: CrmWebhookSubscription[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmWebhookSubscriptionCreate {
  target_url: string;
  event_types: CrmWebhookEventType[];
  secret?: string | null;
  is_active?: boolean;
}

export interface CrmWebhookSubscriptionUpdate {
  target_url?: string;
  event_types?: CrmWebhookEventType[];
  secret?: string | null;
  is_active?: boolean;
}

/** Tags & custom fields */
export interface CrmTag {
  id: string;
  organization_id: string;
  name: string;
  color: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmTagListResponse {
  items: CrmTag[];
  total: number;
  limit: number;
  offset: number;
}

export type CrmEntityType = "deal" | "contact" | "account";
export type CrmFieldType =
  | "text"
  | "number"
  | "date"
  | "boolean"
  | "select"
  | "multiselect"
  | "url";

export interface CrmCustomFieldDefinition {
  id: string;
  organization_id: string;
  entity_type: CrmEntityType;
  field_key: string;
  label: string;
  field_type: CrmFieldType;
  options: string[] | null;
  is_required: boolean;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface CrmCustomFieldListResponse {
  items: CrmCustomFieldDefinition[];
  total: number;
  limit: number;
  offset: number;
}

export interface CrmDealUpdatePayload {
  title?: string;
  custom_fields?: Record<string, unknown>;
  amount?: number | string;
  source?: string | null;
}

export interface CrmDealCreatePayload {
  title: string;
  pipeline_id: string;
  stage_id: string;
  amount?: number | string;
  currency?: string;
  source?: string | null;
}
