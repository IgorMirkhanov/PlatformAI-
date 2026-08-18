/**
 * Typed HTTP client for organization Flow Builder (`/api/v1/flows`).
 */

import { apiRequest } from "@/lib/api";

export interface FlowGraphNode {
  id: string;
  type?: string;
  position?: { x: number; y: number };
  data?: Record<string, unknown> | object;
  [key: string]: unknown;
}

export interface FlowGraphEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  type?: string;
  data?: Record<string, unknown> | object;
  [key: string]: unknown;
}

export interface FlowRecord {
  id: string;
  organization_id: string | null;
  name: string;
  is_active: boolean;
  nodes: FlowGraphNode[];
  edges: FlowGraphEdge[];
  created_at: string;
  updated_at: string;
}

export interface FlowListResponse {
  items: FlowRecord[];
  total: number;
}

export interface FlowCreatePayload {
  name: string;
  is_active?: boolean;
  nodes?: FlowGraphNode[];
  edges?: FlowGraphEdge[];
}

export interface FlowUpdatePayload {
  name?: string;
  is_active?: boolean;
  nodes?: FlowGraphNode[];
  edges?: FlowGraphEdge[];
}

export interface FlowTestRunPayload {
  message?: string;
  sender_id?: string;
  variables?: Record<string, unknown>;
  session_id?: string;
}

export interface FlowTestRunResult {
  session_id: string;
  flow_id: string;
  status: string;
  steps_executed: number;
  path: string[];
  variables: Record<string, unknown>;
  outputs: Array<Record<string, unknown>>;
  error: string | null;
  is_terminal: boolean;
}

export async function getFlows(activeOnly = false): Promise<FlowListResponse> {
  const params = new URLSearchParams();
  if (activeOnly) params.set("active_only", "true");
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<FlowListResponse>(`/api/v1/flows${query}`);
}

export async function getFlow(id: string): Promise<FlowRecord> {
  return apiRequest<FlowRecord>(`/api/v1/flows/${id}`);
}

export async function createFlow(payload: FlowCreatePayload): Promise<FlowRecord> {
  return apiRequest<FlowRecord>("/api/v1/flows", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateFlow(
  id: string,
  payload: FlowUpdatePayload,
): Promise<FlowRecord> {
  return apiRequest<FlowRecord>(`/api/v1/flows/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteFlow(id: string, hard = false): Promise<FlowRecord> {
  const query = hard ? "?hard=true" : "";
  return apiRequest<FlowRecord>(`/api/v1/flows/${id}${query}`, {
    method: "DELETE",
  });
}

export async function testRunFlow(
  id: string,
  payload: FlowTestRunPayload = {},
): Promise<FlowTestRunResult> {
  return apiRequest<FlowTestRunResult>(`/api/v1/flows/${id}/test-run`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
