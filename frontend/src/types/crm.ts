export type CRMPlatform = "amocrm" | "bitrix24";

/** Phase A CRM Action node integration targets. */
export type CRMIntegrationType = "custom_webhook" | "amocrm" | "bitrix24";

export type CRMHttpMethod = "POST" | "GET" | "PUT";

export interface CRMHeaderPair {
  id: string;
  key: string;
  value: string;
}

export interface CRMPlatformStatus {
  platform: CRMPlatform;
  connected: boolean;
  sync_enabled: boolean;
  label: string;
  detail: string | null;
  pipeline_id: string | null;
  stage_id: string | null;
  default_tags: string[];
}

export interface CRMIntegrationStatusResponse {
  bot_id: string;
  platforms: CRMPlatformStatus[];
}

export interface AmoCRMConnectRequest {
  base_domain: string;
  client_id: string;
  client_secret: string;
  authorization_code: string;
  redirect_uri?: string;
}

export interface Bitrix24ConnectRequest {
  webhook_url: string;
}

export interface CRMConnectResponse {
  bot_id: string;
  platform: CRMPlatform;
  connected: boolean;
  sync_enabled: boolean;
  message: string;
}

export interface CRMIntegrationPatchRequest {
  sync_enabled?: boolean;
  pipeline_id?: string;
  stage_id?: string;
  default_tags?: string[];
  base_domain?: string;
  client_id?: string;
  client_secret?: string;
  authorization_code?: string;
  redirect_uri?: string;
  webhook_url?: string;
}

export interface AmoCRMCredentialsForm {
  base_domain: string;
  client_id: string;
  client_secret: string;
  authorization_code: string;
  redirect_uri: string;
}

export interface Bitrix24CredentialsForm {
  webhook_url: string;
}

export interface CRMPipelineMappingForm {
  pipeline_id: string;
  stage_id: string;
  default_tags: string[];
}

export interface CRMPipelineStage {
  id: string;
  name: string;
  pipeline_id: string;
  pipeline_name: string;
}

export interface CRMPipelineListResponse {
  bot_id: string;
  platform: CRMPlatform;
  pipelines: CRMPipelineStage[];
}

/** Canvas data for the CRM Action / Custom Webhook node. */
export interface CRMActionNodeData {
  label: string;
  integration_type: CRMIntegrationType;
  method: CRMHttpMethod;
  url: string;
  headers: CRMHeaderPair[];
  body_template: string;
  response_variable: string;
  /** Legacy / alias of integration_type for older graphs. */
  action_type: string;
  platform: CRMPlatform;
  pipeline_id: string;
  stage_id: string;
  tags: string;
  params: {
    platform: CRMPlatform;
    pipeline_id: string;
    stage_id: string;
    tags: string[];
    provider?: string;
    channel_id?: string;
  };
}

/** Exported CRM node payload persisted in graph_data JSON. */
export interface CRMActionExportData {
  action_type: string;
  integration_type?: CRMIntegrationType;
  method?: CRMHttpMethod;
  url?: string;
  headers?: Record<string, string>;
  body_template?: string;
  response_variable?: string;
  params?: {
    platform?: CRMPlatform;
    pipeline_id?: string;
    stage_id?: string;
    tags?: string[];
    provider?: string;
    channel_id?: string;
  };
}

export function getPlatformStatusMap(
  platforms: CRMPlatformStatus[],
): Record<CRMPlatform, CRMPlatformStatus | undefined> {
  return {
    amocrm: platforms.find((item) => item.platform === "amocrm"),
    bitrix24: platforms.find((item) => item.platform === "bitrix24"),
  };
}

export function buildPipelineOptions(stages: CRMPipelineStage[]): Array<{ id: string; name: string }> {
  const seen = new Set<string>();
  const options: Array<{ id: string; name: string }> = [];
  stages.forEach((stage) => {
    if (seen.has(stage.pipeline_id)) {
      return;
    }
    seen.add(stage.pipeline_id);
    options.push({ id: stage.pipeline_id, name: stage.pipeline_name });
  });
  return options;
}

export function filterStagesForPipeline(
  stages: CRMPipelineStage[],
  pipelineId: string,
): CRMPipelineStage[] {
  return stages.filter((stage) => stage.pipeline_id === pipelineId);
}

export function headersToRecord(headers: CRMHeaderPair[]): Record<string, string> {
  const record: Record<string, string> = {};
  headers.forEach((header) => {
    const key = header.key.trim();
    if (!key) {
      return;
    }
    record[key] = header.value;
  });
  return record;
}

export function recordToHeaders(record: Record<string, string> | undefined): CRMHeaderPair[] {
  if (!record) {
    return [{ id: "h-content-type", key: "Content-Type", value: "application/json" }];
  }
  const entries = Object.entries(record);
  if (entries.length === 0) {
    return [{ id: "h-content-type", key: "Content-Type", value: "application/json" }];
  }
  return entries.map(([key, value], index) => ({
    id: `h-${index}-${key}`,
    key,
    value,
  }));
}
