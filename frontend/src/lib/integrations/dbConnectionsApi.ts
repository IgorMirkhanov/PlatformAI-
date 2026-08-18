/**
 * Typed HTTP client for organization SQL DB connections.
 */

import { apiRequest } from "@/lib/api";

export type DbConnectionType = "postgresql" | "mysql";

export interface DbConnectionRecord {
  id: string;
  organization_id: string;
  name: string;
  db_type: string;
  created_at: string;
  updated_at: string;
  created_by_id: string | null;
}

export interface DbConnectionListResponse {
  items: DbConnectionRecord[];
  total: number;
}

export interface DbConnectionCreatePayload {
  name: string;
  db_type: DbConnectionType;
  connection_string: string;
}

export async function listDbConnections(): Promise<DbConnectionListResponse> {
  return apiRequest<DbConnectionListResponse>("/api/v1/integrations/db-connections");
}

export async function createDbConnection(
  payload: DbConnectionCreatePayload,
): Promise<DbConnectionRecord> {
  return apiRequest<DbConnectionRecord>("/api/v1/integrations/db-connections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteDbConnection(id: string): Promise<void> {
  await apiRequest<void>(`/api/v1/integrations/db-connections/${id}`, {
    method: "DELETE",
  });
}
