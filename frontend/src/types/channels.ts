export type ChannelIntegrationType =
  | "telegram"
  | "whatsapp"
  | "instagram"
  | "vkontakte"
  | "web_widget";

export interface ChannelDefinition {
  id: ChannelIntegrationType;
  title: string;
  subtitle: string;
  description: string;
  brandColor: string;
  brandGradient: string;
  accentRing: string;
  buttonGlow: string;
}

export interface ChannelStatus {
  channel_type: ChannelIntegrationType;
  connected: boolean;
  active: boolean;
  webhook_url?: string | null;
  verify_token?: string | null;
  embed_script?: string | null;
  telegram_username?: string | null;
  metadata?: Record<string, string>;
}

export interface BotChannelsResponse {
  bot_id: string;
  channels: ChannelStatus[];
}

export interface SetupChannelRequest {
  channel_type: ChannelIntegrationType;
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
  platform_type: string;
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

export interface TelegramChannelFormValues {
  telegram_bot_token: string;
  telegram_active: boolean;
}

export interface WhatsAppChannelFormValues {
  whatsapp_phone_number_id: string;
  whatsapp_business_account_id: string;
  whatsapp_access_token: string;
  whatsapp_verify_token: string;
}

export interface InstagramChannelFormValues {
  instagram_page_id: string;
  instagram_access_token: string;
}

export interface VkontakteChannelFormValues {
  vk_group_id: string;
  vk_access_token: string;
}

export interface WebWidgetChannelFormValues {
  web_widget_active: boolean;
}

export const OMNICHANNEL_DEFINITIONS: ChannelDefinition[] = [
  {
    id: "telegram",
    title: "Telegram (бот)",
    subtitle: "Bot API",
    description:
      "Подключите ИИ-агента к Telegram, чтобы он автоматически отвечал на сообщения и вёл диалоги с клиентами.",
    brandColor: "#229ED9",
    brandGradient: "from-[#229ED9]/20 via-[#229ED9]/5 to-transparent",
    accentRing: "ring-[#229ED9]/30",
    buttonGlow: "shadow-[0_0_24px_rgba(34,158,217,0.35)]",
  },
  {
    id: "whatsapp",
    title: "WABA",
    subtitle: "WhatsApp Business API",
    description:
      "Официальный бизнес-аккаунт через API — для массовых рассылок, верификации бренда и корпоративных диалогов.",
    brandColor: "#25D366",
    brandGradient: "from-[#25D366]/20 via-[#128C7E]/5 to-transparent",
    accentRing: "ring-[#25D366]/30",
    buttonGlow: "shadow-[0_0_24px_rgba(37,211,102,0.35)]",
  },
  {
    id: "instagram",
    title: "Instagram",
    subtitle: "Direct Messages",
    description:
      "Подключите ИИ-агента к Instagram Direct, чтобы обрабатывать входящие сообщения и заявки из соцсети.",
    brandColor: "#E4405F",
    brandGradient: "from-[#E4405F]/20 via-[#833AB4]/5 to-transparent",
    accentRing: "ring-[#E4405F]/30",
    buttonGlow: "shadow-[0_0_24px_rgba(228,64,95,0.35)]",
  },
  {
    id: "vkontakte",
    title: "VKontakte",
    subtitle: "Сообщения сообщества",
    description:
      "Интеграция с VK Callback API для автоматических ответов в сообщениях сообщества и диалогах с клиентами.",
    brandColor: "#0077FF",
    brandGradient: "from-[#0077FF]/20 via-[#0077FF]/5 to-transparent",
    accentRing: "ring-[#0077FF]/30",
    buttonGlow: "shadow-[0_0_24px_rgba(0,119,255,0.35)]",
  },
  {
    id: "web_widget",
    title: "Чат для сайта",
    subtitle: "Embeddable Widget",
    description:
      "Встройте MoonAI-виджет на внешний сайт и принимайте обращения клиентов прямо из браузера.",
    brandColor: "#8B5CF6",
    brandGradient: "from-violet-500/20 via-violet-500/5 to-transparent",
    accentRing: "ring-violet-500/30",
    buttonGlow: "shadow-glow-purple",
  },
];

export function getConnectedChannelIds(
  statuses: Record<ChannelIntegrationType, ChannelStatus>,
): ChannelIntegrationType[] {
  return OMNICHANNEL_DEFINITIONS.filter(
    (definition) => statuses[definition.id]?.connected && statuses[definition.id]?.active,
  ).map((definition) => definition.id);
}

export type PatchChannelRequest = Omit<SetupChannelRequest, "channel_type">;

export function buildDefaultChannelMap(): Record<ChannelIntegrationType, ChannelStatus> {
  return {
    telegram: { channel_type: "telegram", connected: false, active: false },
    whatsapp: { channel_type: "whatsapp", connected: false, active: false },
    instagram: { channel_type: "instagram", connected: false, active: false },
    vkontakte: { channel_type: "vkontakte", connected: false, active: false },
    web_widget: { channel_type: "web_widget", connected: false, active: false },
  };
}

export function mergeChannelStatuses(
  channels: ChannelStatus[],
): Record<ChannelIntegrationType, ChannelStatus> {
  const map = buildDefaultChannelMap();
  for (const channel of channels) {
    map[channel.channel_type] = channel;
  }
  return map;
}

export function buildWidgetEmbedScript(botId: string, origin?: string): string {
  const base =
    origin ??
    (typeof window !== "undefined" ? window.location.origin : "https://app.moonai.io");
  return `<script src="${base}/widget.js?id=${botId}" async></script>`;
}
