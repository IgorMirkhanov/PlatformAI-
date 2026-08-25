/** Integration Hub REST client — connections, OAuth authorize URL, testConnection. */

import { apiRequest } from "@/lib/api";
import type { HubConnection, HubProvider } from "@/types/integration-hub";

interface HubConnectionApi {
  id: string;
  provider: string;
  status: string;
  bot_id?: string | null;
  external_account_id?: string | null;
  config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  oauth_expires_at?: string | null;
  last_error?: string | null;
  updated_at?: string;
  workspace_id?: string;
  agent_id?: string | null;
}

function mapConnection(row: HubConnectionApi): HubConnection {
  const meta = row.metadata && typeof row.metadata === "object" ? row.metadata : {};
  return {
    id: row.id,
    provider: row.provider,
    status: row.status,
    botId: row.bot_id ?? null,
    agentId: row.agent_id ?? row.bot_id ?? null,
    workspaceId: row.workspace_id,
    externalAccountId: row.external_account_id ?? null,
    oauthExpiresAt: row.oauth_expires_at ?? null,
    lastError: row.last_error ?? null,
    config: row.config && typeof row.config === "object" ? row.config : {},
    metadata: meta,
  };
}

export async function fetchHubConnections(): Promise<HubConnection[]> {
  const data = await apiRequest<{ connections: HubConnectionApi[] }>(
    "/api/v1/integrations/hub/connections",
  );
  return (data.connections || []).map(mapConnection);
}

export async function connectHubProvider(
  provider: HubProvider | string,
  payload: Record<string, unknown>,
  botId?: string | null,
): Promise<{ connection: HubConnection; message: string }> {
  const data = await apiRequest<{ connection: HubConnectionApi; message: string }>(
    "/api/v1/integrations/hub/connections",
    {
      method: "POST",
      body: JSON.stringify({
        provider,
        bot_id: botId || null,
        payload,
      }),
    },
  );
  return { connection: mapConnection(data.connection), message: data.message };
}

export async function testHubConnection(
  provider: HubProvider | string,
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; metadata?: Record<string, unknown>; external_account_id?: string | null }> {
  return apiRequest("/api/v1/integrations/hub/connections/test", {
    method: "POST",
    body: JSON.stringify({ provider, payload }),
  });
}

export async function disconnectHubConnection(connectionId: string): Promise<void> {
  await apiRequest(`/api/v1/integrations/${encodeURIComponent(connectionId)}/disconnect`, {
    method: "POST",
  });
}

export async function fetchHubAuthorizeUrl(input: {
  provider: "bitrix24" | "amocrm" | "kommo" | string;
  workspaceId: string;
  agentId?: string | null;
  subdomain?: string;
  domain?: string;
}): Promise<string> {
  const params = new URLSearchParams({
    workspace_id: input.workspaceId,
    format: "json",
  });
  if (input.agentId) params.set("agent_id", input.agentId);
  if (input.subdomain) params.set("subdomain", input.subdomain);
  if (input.domain) params.set("domain", input.domain);
  const data = await apiRequest<{ authorize_url: string }>(
    `/api/v1/integrations/${encodeURIComponent(input.provider)}/authorize?${params.toString()}`,
  );
  return data.authorize_url;
}
