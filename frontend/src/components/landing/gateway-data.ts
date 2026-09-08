export type ChangelogStatus = "released" | "in_progress" | "planned";

export interface ChangelogEntry {
  id: string;
  title: string;
  description: string;
  status: ChangelogStatus;
  version?: string;
  date?: string;
}

export interface SystemMetric {
  label: string;
  value: string;
  hint: string;
}

export interface MicroserviceStatus {
  id: string;
  name: string;
  description: string;
  latencyMs?: number;
}

export const SYSTEM_METRICS: SystemMetric[] = [
  { label: "Каналы", value: "6+", hint: "WhatsApp, Telegram, Web, CRM…" },
  { label: "Стек", value: "Prod-ready", hint: "Compose, health-checks, rolling deploy" },
  { label: "Биллинг", value: "Wallet", hint: "Квоты и кредиты workspace" },
];

export const MICROSERVICES: MicroserviceStatus[] = [
  {
    id: "llm",
    name: "LLM Gateway",
    description: "OpenAI-compatible routing, prompt cache, token metering",
  },
  {
    id: "flow",
    name: "Flow Engine",
    description: "State machine, loop guard, CRM & SQL node handlers",
  },
  {
    id: "omni",
    name: "WhatsApp / Telegram",
    description: "Omnichannel connectors, operator inbox, webhooks",
  },
];

export const CHANGELOG_RELEASED: ChangelogEntry[] = [
  {
    id: "flow-builder",
    title: "Визуальный Flow Builder",
    description:
      "Конструктор графов с LLM, условиями, CRM-действиями и публикацией сценариев на агента.",
    status: "released",
    version: "v2.4",
    date: "Июль 2026",
  },
  {
    id: "sql-tenant",
    title: "Secure Tenant Storage для SQL",
    description:
      "Зашифрованные подключения к PostgreSQL/MySQL на уровне организации с SELECT-only узлом.",
    status: "released",
    version: "v2.5",
    date: "Июль 2026",
  },
  {
    id: "native-crm",
    title: "Native CRM + Kanban",
    description: "Воронки, сделки, контакты, автоматизации и исходящие вебхуки.",
    status: "released",
    version: "v2.3",
    date: "Июнь 2026",
  },
];

export const CHANGELOG_IN_PROGRESS: ChangelogEntry[] = [
  {
    id: "google-sheets",
    title: "Интеграция с Google Sheets",
    description: "Узел append_row / read_row с Service Account и маппингом переменных сессии.",
    status: "in_progress",
    version: "v2.6",
    date: "В разработке",
  },
  {
    id: "audit-rate",
    title: "Security Audit & Rate Limits",
    description: "Журнал критических действий, tenant isolation и slowapi 429-защита публичных API.",
    status: "in_progress",
    version: "v2.6",
    date: "В разработке",
  },
  {
    id: "stripe-billing",
    title: "Stripe Wallet & Portal",
    description: "Пополнение баланса в KZT, Customer Portal и история транзакций.",
    status: "planned",
    date: "Q3 2026",
  },
];
