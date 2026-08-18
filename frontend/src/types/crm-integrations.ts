import type { CRMPlatform } from "@/types/crm";

/** Full Integrations-tab catalog (screenshot parity). */
export type AppIntegrationPlatform =
  | CRMPlatform
  | "google_calendar"
  | "kaspi_receipts"
  | "kaspi_pay"
  | "jivo"
  | "uon";

export type IntegrationAvailability = "available" | "on_request";

export interface CRMIntegrationDefinition {
  id: AppIntegrationPlatform;
  title: string;
  description: string;
  brandColor: string;
  brandGradient: string;
  accentRing: string;
  available: boolean;
  availability: IntegrationAvailability;
}

export const CRM_INTEGRATION_DEFINITIONS: CRMIntegrationDefinition[] = [
  {
    id: "amocrm",
    title: "AmoCRM",
    description:
      "ИИ-агент создаёт и заполняет карточки клиентов, двигает этапы сделок.",
    brandColor: "#0061FF",
    brandGradient: "from-[#0061FF]/20 via-[#0061FF]/5 to-transparent",
    accentRing: "ring-[#0061FF]/30",
    available: true,
    availability: "available",
  },
  {
    id: "bitrix24",
    title: "Битрикс 24",
    description:
      "ИИ-агент создаёт и заполняет карточки клиентов, двигает этапы сделок.",
    brandColor: "#2FC6F6",
    brandGradient: "from-[#2FC6F6]/20 via-[#2FC6F6]/5 to-transparent",
    accentRing: "ring-[#2FC6F6]/30",
    available: true,
    availability: "available",
  },
  {
    id: "google_calendar",
    title: "Google Calendar",
    description:
      "ИИ-агент может записывать на просмотры, консультации, созвоны и т.д.",
    brandColor: "#4285F4",
    brandGradient: "from-[#4285F4]/20 via-[#34A853]/5 to-transparent",
    accentRing: "ring-[#4285F4]/30",
    available: true,
    availability: "available",
  },
  {
    id: "kaspi_receipts",
    title: "Проверка Kaspi-чеков",
    description: "Автоматически проверяет подлинность PDF-чеков от клиентов.",
    brandColor: "#F14635",
    brandGradient: "from-[#F14635]/20 via-[#F14635]/5 to-transparent",
    accentRing: "ring-[#F14635]/30",
    available: true,
    availability: "available",
  },
  {
    id: "kaspi_pay",
    title: "Kaspi Pay",
    description:
      "Агент выставляет счёт в диалоге — клиент получает уведомление в Kaspi.",
    brandColor: "#F14635",
    brandGradient: "from-[#F14635]/25 via-[#111]/5 to-transparent",
    accentRing: "ring-[#F14635]/30",
    available: true,
    availability: "available",
  },
  {
    id: "jivo",
    title: "Jivo",
    description:
      "Агент отвечает на обращения из чата сайта, мессенджеров и соцсетей.",
    brandColor: "#FFE566",
    brandGradient: "from-[#FFE566]/25 via-[#111]/5 to-transparent",
    accentRing: "ring-[#FFE566]/30",
    available: true,
    availability: "available",
  },
  {
    id: "uon",
    title: "U-ON",
    description:
      "Агент записывает заявки туристов в CRM: контакты, направление, даты, бюджет.",
    brandColor: "#00A0E3",
    brandGradient: "from-[#00A0E3]/20 via-[#00A0E3]/5 to-transparent",
    accentRing: "ring-[#00A0E3]/30",
    available: true,
    availability: "available",
  },
];

export interface AppIntegrationPlatformStatus {
  platform: AppIntegrationPlatform;
  connected: boolean;
  sync_enabled: boolean;
  label: string;
  detail: string | null;
  availability?: IntegrationAvailability;
  webhook_url?: string | null;
  meta?: Record<string, unknown>;
}

export interface AppIntegrationsStatusResponse {
  bot_id: string;
  platforms: AppIntegrationPlatformStatus[];
}

export interface AppIntegrationConnectPayload {
  base_domain?: string;
  client_id?: string;
  client_secret?: string;
  authorization_code?: string;
  redirect_uri?: string;
  webhook_url?: string;
  refresh_token?: string;
  access_token?: string;
  calendar_id?: string;
  merchant_id?: string;
  merchant_token?: string;
  api_key?: string;
  secret_key?: string;
  token?: string;
  provider_id?: string;
  base_url?: string;
  mode?: string;
  min_amount_kzt?: number;
  payment_base_url?: string;
  sync_enabled?: boolean;
}

