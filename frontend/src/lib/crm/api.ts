/**
 * Typed HTTP client for native CRM endpoints (`/api/v1/crm/*`).
 * Reuses shared `apiRequest` so JWT / org headers are applied automatically.
 */

import { apiRequest } from "@/lib/api";
import type {
  CrmAutomationRule,
  CrmAutomationRuleCreate,
  CrmAutomationRuleListResponse,
  CrmAutomationRuleUpdate,
  CrmContact,
  CrmContactListResponse,
  CrmCustomFieldDefinition,
  CrmCustomFieldListResponse,
  CrmDeal,
  CrmDealCreatePayload,
  CrmDealListResponse,
  CrmDealUpdatePayload,
  CrmForecastResponse,
  CrmFunnelResponse,
  CrmNote,
  CrmNoteListResponse,
  CrmPerformanceResponse,
  CrmPipeline,
  CrmTag,
  CrmTagListResponse,
  CrmTimelineEvent,
  CrmTimelineListResponse,
  CrmWebhookSubscription,
  CrmWebhookSubscriptionCreate,
  CrmWebhookSubscriptionListResponse,
  CrmWebhookSubscriptionUpdate,
} from "@/lib/crm/types";

export type {
  Contact,
  CrmAutomationRule,
  CrmAutomationTriggerType,
  CrmContact,
  CrmContactBrief,
  CrmContactListResponse,
  CrmCustomFieldDefinition,
  CrmDeal,
  CrmDealListResponse,
  CrmDealStatus,
  CrmForecastResponse,
  CrmFunnelResponse,
  CrmFunnelStageStat,
  CrmManagerPerformanceRow,
  CrmNote,
  CrmPerformanceResponse,
  CrmPipeline,
  CrmStage,
  CrmTag,
  CrmTimelineEvent,
  CrmWebhookEventType,
  CrmWebhookSubscription,
  Deal,
  Pipeline,
  Stage,
} from "@/lib/crm/types";

export async function getPipelines(): Promise<CrmPipeline[]> {
  return apiRequest<CrmPipeline[]>("/api/v1/crm/pipelines");
}

export async function getDeals(pipelineId: string): Promise<CrmDeal[]> {
  const params = new URLSearchParams({
    pipeline_id: pipelineId,
    limit: "200",
  });
  const response = await apiRequest<CrmDealListResponse>(
    `/api/v1/crm/deals?${params.toString()}`,
  );
  return response.items;
}

export async function getDeal(dealId: string): Promise<CrmDeal> {
  return apiRequest<CrmDeal>(`/api/v1/crm/deals/${dealId}`);
}

export async function createDeal(payload: CrmDealCreatePayload): Promise<CrmDeal> {
  return apiRequest<CrmDeal>("/api/v1/crm/deals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateDeal(
  dealId: string,
  payload: CrmDealUpdatePayload,
): Promise<CrmDeal> {
  return apiRequest<CrmDeal>(`/api/v1/crm/deals/${dealId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function moveDealStage(
  dealId: string,
  stageId: string,
): Promise<CrmDeal> {
  return apiRequest<CrmDeal>(`/api/v1/crm/deals/${dealId}/move-stage`, {
    method: "POST",
    body: JSON.stringify({ stage_id: stageId }),
  });
}

export async function getTimeline(dealId: string): Promise<CrmTimelineEvent[]> {
  const params = new URLSearchParams({
    deal_id: dealId,
    limit: "200",
  });
  const response = await apiRequest<CrmTimelineListResponse>(
    `/api/v1/crm/timeline?${params.toString()}`,
  );
  return response.items;
}

export async function getNotes(dealId: string): Promise<CrmNote[]> {
  const params = new URLSearchParams({
    deal_id: dealId,
    limit: "200",
  });
  const response = await apiRequest<CrmNoteListResponse>(
    `/api/v1/crm/notes?${params.toString()}`,
  );
  return response.items;
}

export async function addNote(dealId: string, text: string): Promise<CrmNote> {
  return apiRequest<CrmNote>("/api/v1/crm/notes", {
    method: "POST",
    body: JSON.stringify({ deal_id: dealId, text }),
  });
}

export async function getContacts(
  page = 1,
  limit = 20,
  search?: string,
): Promise<CrmContactListResponse> {
  const offset = Math.max(0, (page - 1) * limit);
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (search?.trim()) {
    params.set("q", search.trim());
  }
  return apiRequest<CrmContactListResponse>(
    `/api/v1/crm/contacts?${params.toString()}`,
  );
}

export async function getContact(contactId: string): Promise<CrmContact> {
  return apiRequest<CrmContact>(`/api/v1/crm/contacts/${contactId}`);
}

export async function getCrmFunnel(
  pipelineId: string,
  startDate?: string,
  endDate?: string,
): Promise<CrmFunnelResponse> {
  const params = new URLSearchParams({ pipeline_id: pipelineId });
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return apiRequest<CrmFunnelResponse>(
    `/api/v1/crm/analytics/funnel?${params.toString()}`,
  );
}

export async function getCrmPerformance(
  startDate?: string,
  endDate?: string,
): Promise<CrmPerformanceResponse> {
  const params = new URLSearchParams();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  const qs = params.toString();
  return apiRequest<CrmPerformanceResponse>(
    `/api/v1/crm/analytics/performance${qs ? `?${qs}` : ""}`,
  );
}

export async function getCrmForecast(): Promise<CrmForecastResponse> {
  return apiRequest<CrmForecastResponse>("/api/v1/crm/analytics/forecast");
}

export async function listAutomationRules(
  activeOnly?: boolean,
): Promise<CrmAutomationRuleListResponse> {
  const params = new URLSearchParams({ limit: "200" });
  if (activeOnly !== undefined) params.set("is_active", String(activeOnly));
  return apiRequest<CrmAutomationRuleListResponse>(
    `/api/v1/crm/automations?${params.toString()}`,
  );
}

export async function createAutomationRule(
  payload: CrmAutomationRuleCreate,
): Promise<CrmAutomationRule> {
  return apiRequest<CrmAutomationRule>("/api/v1/crm/automations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAutomationRule(
  ruleId: string,
  payload: CrmAutomationRuleUpdate,
): Promise<CrmAutomationRule> {
  return apiRequest<CrmAutomationRule>(`/api/v1/crm/automations/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteAutomationRule(ruleId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/crm/automations/${ruleId}`, {
    method: "DELETE",
  });
}

export async function listWebhookSubscriptions(): Promise<CrmWebhookSubscriptionListResponse> {
  return apiRequest<CrmWebhookSubscriptionListResponse>(
    "/api/v1/crm/webhooks?limit=200",
  );
}

export async function createWebhookSubscription(
  payload: CrmWebhookSubscriptionCreate,
): Promise<CrmWebhookSubscription> {
  return apiRequest<CrmWebhookSubscription>("/api/v1/crm/webhooks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateWebhookSubscription(
  id: string,
  payload: CrmWebhookSubscriptionUpdate,
): Promise<CrmWebhookSubscription> {
  return apiRequest<CrmWebhookSubscription>(`/api/v1/crm/webhooks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteWebhookSubscription(id: string): Promise<void> {
  await apiRequest<void>(`/api/v1/crm/webhooks/${id}`, {
    method: "DELETE",
  });
}

export async function listCrmTags(): Promise<CrmTag[]> {
  const response = await apiRequest<CrmTagListResponse>(
    "/api/v1/crm/tags?limit=200",
  );
  return response.items;
}

export async function attachDealTag(
  dealId: string,
  tagId: string,
): Promise<CrmTag> {
  return apiRequest<CrmTag>(`/api/v1/crm/deals/${dealId}/tags/${tagId}`, {
    method: "POST",
  });
}

export async function removeDealTag(
  dealId: string,
  tagId: string,
): Promise<void> {
  await apiRequest<void>(`/api/v1/crm/deals/${dealId}/tags/${tagId}`, {
    method: "DELETE",
  });
}

export async function listCustomFields(
  entityType: "deal" | "contact" | "account" = "deal",
): Promise<CrmCustomFieldDefinition[]> {
  const params = new URLSearchParams({
    entity_type: entityType,
    limit: "200",
  });
  const response = await apiRequest<CrmCustomFieldListResponse>(
    `/api/v1/crm/custom-fields?${params.toString()}`,
  );
  return response.items;
}
