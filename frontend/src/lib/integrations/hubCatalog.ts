import type { HubAuthKind, HubCardState, HubConnection, HubProvider } from "@/types/integration-hub";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import { CRM_INTEGRATION_DEFINITIONS } from "@/types/crm-integrations";

export interface HubCardProvider {
  id: HubProvider;
  title: string;
  description: string;
  auth: HubAuthKind;
  logo: string;
  brandColor: string;
  brandGradient: string;
  accentRing: string;
  permissions: string[];
  oauthHint?: string;
}

function fromCrm(id: HubProvider): Pick<
  CRMIntegrationDefinition,
  "title" | "description" | "brandColor" | "brandGradient" | "accentRing"
> {
  const row = CRM_INTEGRATION_DEFINITIONS.find((item) => item.id === id);
  if (!row) {
    return {
      title: id,
      description: "",
      brandColor: "#a78bfa",
      brandGradient: "from-violet-500/20 via-transparent to-transparent",
      accentRing: "ring-violet-500/30",
    };
  }
  return {
    title: row.title,
    description: row.description,
    brandColor: row.brandColor,
    brandGradient: row.brandGradient,
    accentRing: row.accentRing,
  };
}

export const HUB_CARD_PROVIDERS: HubCardProvider[] = [
  {
    id: "bitrix24",
    ...fromCrm("bitrix24"),
    auth: "webhook",
    logo: "B24",
    permissions: ["Контакты", "Сделки", "Комментарии в таймлайне"],
    oauthHint: "Incoming webhook URL из Bitrix24 → Разработчикам → Другое",
  },
  {
    id: "amocrm",
    ...fromCrm("amocrm"),
    auth: "oauth",
    logo: "amo",
    permissions: ["Контакты", "Сделки", "Примечания"],
    oauthHint: "Поддомен аккаунта, например acme",
  },
  {
    id: "wazzup",
    title: "Wazzup",
    description: "WhatsApp, Telegram и Instagram через один API-ключ.",
    brandColor: "#22c55e",
    brandGradient: "from-emerald-500/20 via-transparent to-transparent",
    accentRing: "ring-emerald-500/30",
    auth: "api_key",
    logo: "Wz",
    permissions: ["Входящие сообщения", "Исходящие сообщения", "Каналы WhatsApp / Telegram / Instagram"],
  },
  {
    id: "kaspi_pay",
    ...fromCrm("kaspi_pay"),
    auth: "api_key",
    logo: "KP",
    permissions: ["Выставление счетов", "Статус оплаты по webhook"],
  },
];

export const HUB_CARD_PROVIDER_IDS: ReadonlySet<string> = new Set(
  HUB_CARD_PROVIDERS.map((item) => item.id),
);

export function mapHubCardState(
  status: string | null | undefined,
  localConnecting: boolean,
  localError?: boolean,
): HubCardState {
  if (localConnecting) return "connecting";
  if (localError) return "error";
  const key = (status || "disconnected").toLowerCase();
  if (key === "connected") return "connected";
  if (key === "expired") return "expired";
  if (key === "error") return "error";
  if (key === "pending") return "connecting";
  // revoked / disconnected / unknown → clean reconnect CTA
  return "not_connected";
}

export function hubAccountLabel(input: {
  externalAccountId?: string | null;
  config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}): string | null {
  const config = input.config || {};
  const metadata = input.metadata || {};
  const subdomain = String(config.subdomain || metadata.subdomain || "").trim();
  const domain = String(
    config.domain || config.client_endpoint || metadata.domain || metadata.portal || "",
  ).trim();
  if (subdomain) return subdomain.includes(".") ? subdomain : `${subdomain}.amocrm.ru`;
  if (domain) return domain.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const merchant = String(config.merchant_id || metadata.merchant_id || "").trim();
  if (merchant) return `Merchant ${merchant}`;
  const accountName = String(metadata.account_name || metadata.name || "").trim();
  if (accountName) return accountName;
  if (input.externalAccountId) return String(input.externalAccountId);
  return null;
}

export function pickHubConnection(
  connections: HubConnection[],
  provider: string,
  botId?: string | null,
): HubConnection | null {
  const rows = connections.filter((row) => String(row.provider) === provider);
  if (rows.length === 0) return null;
  if (botId) {
    const scoped = rows.find((row) => row.botId === botId || row.agentId === botId);
    if (scoped) return scoped;
  }
  return rows.find((row) => !row.botId && !row.agentId) ?? rows[0] ?? null;
}
