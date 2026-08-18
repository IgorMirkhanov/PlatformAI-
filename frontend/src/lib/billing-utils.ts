import type { BillingCurrency, BillingTransactionStatus, SubscriptionPlanName } from "@/types/billing";

export function formatBillingCurrency(
  value: number,
  currency: BillingCurrency = "KZT",
): string {
  if (currency === "USD") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  return new Intl.NumberFormat("ru-KZ", {
    style: "currency",
    currency: "KZT",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatBillingAmountSigned(value: number, currency: BillingCurrency = "KZT"): string {
  const formatted = formatBillingCurrency(Math.abs(value), currency);
  if (value > 0) {
    return `+${formatted}`;
  }
  if (value < 0) {
    return `−${formatted}`;
  }
  return formatted;
}

export function formatTransactionDate(isoDate: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(isoDate));
}

export function formatShortTransactionId(id: string): string {
  return id.replace(/-/g, "").slice(0, 8).toUpperCase();
}

export function formatPlanExpiryLabel(
  expiresAt: string | null,
  daysRemaining: number | null,
): string {
  if (daysRemaining !== null && daysRemaining !== undefined) {
    if (daysRemaining === 0) {
      return "Подписка истекает сегодня";
    }
    return `Окончание подписки через ${daysRemaining} ${pluralizeDays(daysRemaining)}`;
  }

  if (expiresAt) {
    return `Подписка активна до ${new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(expiresAt))}`;
  }

  return "Бессрочный тариф FREE";
}

export function formatRenewalDate(expiresAt: string | null): string | null {
  if (!expiresAt) {
    return null;
  }

  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(expiresAt));
}

export function getTransactionStatusClassName(status: BillingTransactionStatus): string {
  switch (status) {
    case "SUCCESS":
      return "text-emerald-400 ring-emerald-500/25 bg-emerald-500/10";
    case "PENDING":
      return "text-amber-300 ring-amber-500/25 bg-amber-500/10";
    case "FAILED":
      return "text-rose-400 ring-rose-500/25 bg-rose-500/10";
    default:
      return "text-zinc-400 ring-zinc-700 bg-zinc-800/80";
  }
}

export function getPlanProgressPercent(daysRemaining: number | null, plan: SubscriptionPlanName): number {
  const cycleDays = plan === "FREE" ? 365 : 30;
  if (daysRemaining === null || daysRemaining === undefined) {
    return plan === "FREE" ? 100 : 72;
  }
  return Math.max(8, Math.min(100, Math.round((daysRemaining / cycleDays) * 100)));
}

function pluralizeDays(value: number): string {
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return "день";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "дня";
  return "дней";
}
