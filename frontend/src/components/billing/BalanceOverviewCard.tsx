"use client";

import { Gift } from "lucide-react";

import {
  formatBillingCurrency,
  formatPlanExpiryLabel,
  formatRenewalDate,
  getPlanProgressPercent,
} from "@/lib/billing-utils";
import type { BillingCurrency, SubscriptionPlanName } from "@/types/billing";

interface BalanceOverviewCardProps {
  balance: number;
  bonusBalance: number;
  currency: BillingCurrency;
  planName: SubscriptionPlanName;
  daysRemaining: number | null;
  expiresAt: string | null;
  statusLabel: string;
  loading?: boolean;
}

export function BalanceOverviewCard({
  balance,
  bonusBalance,
  currency,
  planName,
  daysRemaining,
  expiresAt,
  statusLabel,
  loading = false,
}: BalanceOverviewCardProps) {
  const progress = getPlanProgressPercent(daysRemaining, planName);
  const renewalDate = formatRenewalDate(expiresAt);

  return (
    <section className="relative overflow-hidden rounded-2xl border border-violet-500/20 bg-zinc-950/60 p-6 backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-violet-500/10 via-transparent to-indigo-500/5" />

      {loading ? (
        <div className="relative space-y-4 animate-pulse">
          <div className="h-4 w-32 rounded bg-zinc-800/80" />
          <div className="h-12 w-48 rounded bg-zinc-800/80" />
          <div className="h-3 w-full rounded bg-zinc-800/60" />
        </div>
      ) : (
        <div className="relative">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
                Основной баланс
              </p>
              <p className="mt-2 text-4xl font-bold tracking-tight text-white md:text-5xl">
                {formatBillingCurrency(balance, currency)}
              </p>
              {bonusBalance > 0 ? (
                <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-violet-500/15 px-3 py-1 text-xs font-medium text-violet-200 ring-1 ring-violet-500/25">
                  <Gift className="h-3.5 w-3.5" />
                  {formatBillingCurrency(bonusBalance, currency)} бонусов
                </div>
              ) : null}
            </div>

            <div className="rounded-xl border border-zinc-800/80 bg-black/30 px-4 py-3 text-right">
              <p className="text-[10px] uppercase tracking-wide text-zinc-500">Текущий тариф</p>
              <p className="mt-1 text-lg font-semibold text-violet-200">{planName}</p>
              <p className="mt-1 text-xs text-zinc-500">{statusLabel}</p>
            </div>
          </div>

          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between gap-3 text-xs text-zinc-500">
              <span>{formatPlanExpiryLabel(expiresAt, daysRemaining)}</span>
              {renewalDate ? <span>Продление {renewalDate}</span> : null}
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800/80">
              <div
                className="h-full rounded-full bg-gradient-to-r from-violet-600 to-indigo-500 transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
