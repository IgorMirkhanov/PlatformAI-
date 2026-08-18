export type PlatformType = "TELEGRAM" | "WHATSAPP" | "INSTAGRAM" | "VKONTAKTE" | "WEB_WIDGET";

export interface BotHealthTelemetry {
  bot_id: string;
  bot_name: string;
  platform_type: PlatformType;
  is_active: boolean;
  channel_connected: boolean;
  flow_published: boolean;
  validation_status: "valid" | "invalid" | "missing" | string;
  node_count: number;
  edge_count: number;
  flow_updated_at: string | null;
  webhook_url: string | null;
  issues: Array<{
    code: string;
    message: string;
    node_id?: string | null;
    edge_id?: string | null;
    button_id?: string | null;
  }>;
}
