export type HubChannelType =
  | "telegram"
  | "telegram_business"
  | "wazzup"
  | "whatsapp_qr"
  | "instagram"
  | "waba"
  | "calls"
  | "api"
  | "web_widget";

export type HubChannelStatus = "connected" | "disconnected" | "pending";

export interface HubChannelStatusItem {
  channel_type: HubChannelType;
  status: HubChannelStatus;
  connected: boolean;
  reference_id: string | null;
  meta_data: Record<string, unknown>;
  updated_at: string | null;
  webhook_url: string | null;
}

export interface HubChannelsResponse {
  success?: boolean;
  bot_id: string;
  channels: HubChannelStatusItem[];
}

export interface ChannelConnectRequest {
  token?: string;
  reference_id?: string;
  phone_number_id?: string;
  business_account_id?: string;
  access_token?: string;
  verify_token?: string;
  page_id?: string;
  api_key?: string;
  meta_data?: Record<string, unknown>;
}

export interface ChannelConnectResponse {
  success?: boolean;
  bot_id: string;
  channel_type: HubChannelType;
  status: HubChannelStatus;
  connected: boolean;
  reference_id: string | null;
  webhook_url: string | null;
  message: string;
}

export interface ChannelDisconnectResponse {
  success?: boolean;
  bot_id: string;
  channel_type: HubChannelType;
  status: HubChannelStatus;
  connected: boolean;
  message: string;
}

export type WhatsAppQrEvent =
  | "QR_READY"
  | "CONNECTED"
  | "DISCONNECTED"
  | "AUTH_FAILURE"
  | "qr_code_ready"
  | "scanning_detected"
  | "session_connected"
  | "connection_failed";

export interface WhatsAppQrWsFrame {
  event: WhatsAppQrEvent | string;
  legacy_event?: string | null;
  status: string;
  qr_base64: string | null;
  message: string | null;
  reference_id: string | null;
  session_id: string | null;
  push_name?: string | null;
  connected_at?: string | null;
}

export interface WhatsAppSessionStatus {
  bot_id: string;
  status: string;
  phone: string | null;
  push_name: string | null;
  connected_at: string | null;
  has_qr: boolean;
  hub_connected: boolean;
  hub_reference_id: string | null;
}

export interface HubChannelNavItem {
  id: HubChannelType;
  href: string;
  label: string;
  shortLabel: string;
  description: string;
  accent: string;
}

/** Order matches MoonAI Channels screenshot catalog. */
export const HUB_CHANNEL_NAV: HubChannelNavItem[] = [
  {
    id: "telegram",
    href: "telegram",
    label: "Telegram (бот)",
    shortLabel: "TG",
    description: "Bot API через @BotFather",
    accent: "#229ED9",
  },
  {
    id: "telegram_business",
    href: "telegram-secretary",
    label: "Telegram (личный)",
    shortLabel: "TB",
    description: "Личный аккаунт / Business",
    accent: "#5AC8FA",
  },
  {
    id: "wazzup",
    href: "wazzup",
    label: "Wazzup",
    shortLabel: "WZ",
    description: "Агрегатор мессенджеров",
    accent: "#7C3AED",
  },
  {
    id: "whatsapp_qr",
    href: "whatsapp-qr",
    label: "WhatsApp",
    shortLabel: "WA",
    description: "Личный номер по QR",
    accent: "#25D366",
  },
  {
    id: "instagram",
    href: "instagram",
    label: "Instagram",
    shortLabel: "IG",
    description: "Direct Messages",
    accent: "#E4405F",
  },
  {
    id: "waba",
    href: "waba",
    label: "WABA",
    shortLabel: "WABA",
    description: "WhatsApp Business API",
    accent: "#128C7E",
  },
  {
    id: "calls",
    href: "calls",
    label: "Звонки",
    shortLabel: "SIP",
    description: "SIP / телефония",
    accent: "#F59E0B",
  },
  {
    id: "api",
    href: "api",
    label: "API",
    shortLabel: "API",
    description: "HTTP API для внешних систем",
    accent: "#6366F1",
  },
  {
    id: "web_widget",
    href: "web-widget",
    label: "Чат для сайта",
    shortLabel: "Web",
    description: "Встраиваемый виджет",
    accent: "#8B5CF6",
  },
];

export function mergeHubStatuses(
  channels: HubChannelStatusItem[] | undefined,
): Record<HubChannelType, HubChannelStatusItem> {
  const base = Object.fromEntries(
    HUB_CHANNEL_NAV.map((item) => [
      item.id,
      {
        channel_type: item.id,
        status: "disconnected" as HubChannelStatus,
        connected: false,
        reference_id: null,
        meta_data: {},
        updated_at: null,
        webhook_url: null,
      },
    ]),
  ) as Record<HubChannelType, HubChannelStatusItem>;

  for (const channel of channels || []) {
    base[channel.channel_type] = channel;
  }
  return base;
}

