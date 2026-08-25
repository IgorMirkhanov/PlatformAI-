export type SubscriptionPlanName = "FREE" | "PRO" | "ENTERPRISE";
export type SubscriptionStatus = "ACTIVE" | "EXPIRED";
export type BillingCurrency = "KZT" | "USD";
export type BillingTransactionType =
  | "TOP_UP"
  | "SUBSCRIPTION_CHARGE"
  | "LLM_DEDUCTION"
  | "BONUS"
  | "REFUND"
  | "MANUAL_DEPOSIT"
  | "CARD_DEPOSIT";
export type BillingTransactionStatus =
  | "SUCCESS"
  | "PENDING"
  | "FAILED"
  | "APPROVED"
  | "REJECTED";
export type BillingWorkspaceSection = "balance" | "subscriptions" | "agents" | "history" | "payments";

export type SystemNotificationSeverity = "INFO" | "WARNING" | "CRITICAL";
export type SystemNotificationCategory = "BILLING_DEPOSIT" | "SYSTEM";

export interface BillingStatusResponse {
  user_id: string;
  plan_name: SubscriptionPlanName;
  balance: number;
  bonus_balance: number;
  currency: BillingCurrency;
  status: SubscriptionStatus;
  expires_at: string | null;
  days_remaining: number | null;
  active_agents_limit: number;
  is_low_balance?: boolean;
  low_balance_threshold_kzt?: number;
  message: string;
}

export interface SubscribeRequest {
  plan_name: SubscriptionPlanName;
  user_id?: string;
  mock_payment_reference?: string;
}

export interface SubscribeResponse {
  subscription: {
    id: string;
    user_id: string;
    plan_name: SubscriptionPlanName;
    balance: number;
    status: SubscriptionStatus;
    expires_at: string | null;
    created_at: string;
    updated_at: string;
  };
  message: string;
}

export interface BalanceTopUpRequest {
  amount: number;
  user_id?: string;
}

export interface BillingTransaction {
  id: string;
  user_id: string;
  organization_id?: string | null;
  subscription_id: string | null;
  transaction_type: BillingTransactionType;
  amount: number;
  currency: BillingCurrency;
  description: string;
  receipt_url?: string | null;
  status: BillingTransactionStatus;
  reference_id: string | null;
  created_at: string;
}

export interface BillingTransactionListResponse {
  transactions: BillingTransaction[];
  total: number;
}

export interface DepositRequestPayload {
  amount: number;
  receipt: File;
}

export interface DepositRequestResponse {
  id: string;
  organization_id: string | null;
  amount: number;
  currency: BillingCurrency;
  receipt_url: string;
  status: BillingTransactionStatus;
  message: string;
  created_at: string;
}

export interface CardTopupRequest {
  amount: number;
  currency?: BillingCurrency;
  provider?: "stripe" | "tiptop";
  use_saved_card?: boolean;
  tiptop_token?: string;
  widget_mode?: boolean;
  success_url?: string;
  cancel_url?: string;
}

export interface CardTopupResponse {
  status: "redirect" | "processing" | "widget" | string;
  checkout_url?: string;
  payment_url?: string;
  invoice_id?: string;
  message?: string;
  widget_params?: {
    public_id?: string;
    amount?: number;
    currency?: string;
    invoice_id?: string;
    description?: string;
  };
}

export interface SavedTipTopPaymentMethod {
  provider: string;
  has_saved_card: boolean;
  card_last_four?: string | null;
  card_type?: string | null;
}

export interface SystemNotificationRead {
  id: string;
  organization_id: string | null;
  actor_user_id: string | null;
  category: SystemNotificationCategory;
  severity: SystemNotificationSeverity;
  title: string;
  message: string;
  reference_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface SystemNotificationListResponse {
  notifications: SystemNotificationRead[];
  total: number;
  unread_critical: number;
}

export interface PricingTierFeature {
  id: string;
  label: string;
  value: string;
}

export interface PricingTier {
  id: SubscriptionPlanName;
  name: string;
  nameRu: string;
  priceLabel: string;
  priceAmount: number;
  description: string;
  features: PricingTierFeature[];
  highlighted?: boolean;
  badgeLabel?: string;
  agentLimit: number;
  tokenVolume: string;
  ragStorage: string;
  customFunctions: boolean;
}

export interface BillingWorkspaceNavItem {
  id: BillingWorkspaceSection;
  label: string;
  description: string;
}

export const DEFAULT_BILLING_CURRENCY: BillingCurrency = "KZT";

export const TOP_UP_PRESETS_KZT = [5000, 15000, 50000] as const;

export const TOP_UP_PRESETS_USD = [10, 25, 50, 100] as const;

export const ACCEPTED_RECEIPT_MIME_TYPES = [
  "image/png",
  "image/jpeg",
  "image/jpg",
  "application/pdf",
] as const;

export const MANUAL_DEPOSIT_PAYMENT_DETAILS = {
  title: "Реквизиты для безналичного перевода (B2B)",
  kaspi: {
    label: "Kaspi перевод / QR",
    value: "Перевод на Kaspi Business — MP.AI Platform",
    hint: "В комментарии укажите email аккаунта и название организации",
  },
  bank: {
    label: "Банковский перевод (KZT)",
    beneficiary: "ТОО «MP.AI Platform»",
    bin: "Запросите у billing@mp.ai",
    iik: "Запросите у billing@mp.ai",
    bik: "CASPKZKA",
    bankName: "АО «Kaspi Bank»",
  },
} as const;

export const BILLING_WORKSPACE_NAV: BillingWorkspaceNavItem[] = [
  {
    id: "balance",
    label: "Баланс",
    description: "Основной счёт и пополнение",
  },
  {
    id: "subscriptions",
    label: "Подписки",
    description: "Тарифные планы MoonAI",
  },
  {
    id: "agents",
    label: "Агенты в подписке",
    description: "Лимиты активных агентов",
  },
  {
    id: "history",
    label: "История",
    description: "Финансовый журнал операций",
  },
  {
    id: "payments",
    label: "Способы оплаты",
    description: "Карты и реквизиты",
  },
];

export const PRICING_TIERS: PricingTier[] = [
  {
    id: "FREE",
    name: "Free",
    nameRu: "FREE",
    priceLabel: "0 ₸ / мес",
    priceAmount: 0,
    description: "Стартовый тариф для первого агента и базовых сценариев.",
    agentLimit: 1,
    tokenVolume: "100 000 токенов / мес",
    ragStorage: "500 MB RAG",
    customFunctions: false,
    features: [
      { id: "agents", label: "Лимит активных ботов", value: "1 агент" },
      { id: "tokens", label: "Объём AI-токенов", value: "100 000 / мес" },
      { id: "rag", label: "RAG-хранилище", value: "500 MB" },
      { id: "functions", label: "Custom functions", value: "Недоступно" },
    ],
  },
  {
    id: "PRO",
    name: "Pro",
    nameRu: "PRO",
    priceLabel: "24 500 ₸ / мес",
    priceAmount: 24500,
    description: "Оптимальный тариф для omnichannel-операций и масштабирования.",
    highlighted: true,
    badgeLabel: "Популярный",
    agentLimit: 10,
    tokenVolume: "2 000 000 токенов / мес",
    ragStorage: "10 GB RAG",
    customFunctions: true,
    features: [
      { id: "agents", label: "Лимит активных ботов", value: "10 агентов" },
      { id: "tokens", label: "Объём AI-токенов", value: "2 000 000 / мес" },
      { id: "rag", label: "RAG-хранилище", value: "10 GB" },
      { id: "functions", label: "Custom functions", value: "Полный доступ" },
    ],
  },
  {
    id: "ENTERPRISE",
    name: "Enterprise",
    nameRu: "ENTERPRISE",
    priceLabel: "99 000 ₸ / мес",
    priceAmount: 99000,
    description: "Корпоративный контур с расширенными лимитами и SLA.",
    agentLimit: 999,
    tokenVolume: "Без ограничений",
    ragStorage: "Unlimited RAG",
    customFunctions: true,
    features: [
      { id: "agents", label: "Лимит активных ботов", value: "Без ограничений" },
      { id: "tokens", label: "Объём AI-токенов", value: "Unlimited" },
      { id: "rag", label: "RAG-хранилище", value: "Unlimited" },
      { id: "functions", label: "Custom functions", value: "Dedicated runtime" },
    ],
  },
];

export const TRANSACTION_STATUS_LABELS: Record<BillingTransactionStatus, string> = {
  SUCCESS: "Успешно",
  PENDING: "В обработке",
  FAILED: "Ошибка",
  APPROVED: "Одобрено",
  REJECTED: "Отклонено",
};

export const TRANSACTION_TYPE_LABELS: Record<BillingTransactionType, string> = {
  TOP_UP: "Пополнение",
  SUBSCRIPTION_CHARGE: "Списание",
  LLM_DEDUCTION: "LLM Deduction",
  BONUS: "Бонус",
  REFUND: "Возврат",
  MANUAL_DEPOSIT: "Ручное пополнение",
  CARD_DEPOSIT: "Пополнение картой",
};

export const PLAN_BADGE_STYLES: Record<
  SubscriptionPlanName,
  { badge: string; accent: string; border: string }
> = {
  FREE: {
    badge: "bg-zinc-800/80 text-zinc-300 ring-zinc-700/80",
    accent: "text-zinc-200",
    border: "border-zinc-800/80",
  },
  PRO: {
    badge: "bg-violet-500/15 text-violet-200 ring-violet-500/30",
    accent: "text-violet-300",
    border: "border-violet-500/30",
  },
  ENTERPRISE: {
    badge: "bg-amber-500/15 text-amber-200 ring-amber-500/30",
    accent: "text-amber-300",
    border: "border-amber-500/25",
  },
};
