"use client";

import { Building2, Crown, Plus, Wallet } from "lucide-react";

import { formatBillingCurrency, getPlanProgressPercent } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { PLAN_BADGE_STYLES, type BillingCurrency, type SubscriptionPlanName } from "@/types/billing";

interface DashboardHeroHeaderProps {
  companyName: string;
  workspaceId: string;
  balance: number;
  currency: BillingCurrency;
  plan: SubscriptionPlanName;
  daysRemaining: number | null;
  agentsUsed: number;
  agentsLimit: number;
  onTopUpClick: () => void;
}

const PLAN_LABELS: Record<SubscriptionPlanName, string> = {
  FREE: "FREE Plan",
  PRO: "PRO Plan",
  ENTERPRISE: "ENTERPRISE Plan",
};

export function DashboardHeroHeader({
  companyName,
  workspaceId,
  balance,
  currency,
  plan,
  daysRemaining,
  agentsUsed,
  agentsLimit,
  onTopUpClick,
}: DashboardHeroHeaderProps) {
  const planStyles = PLAN_BADGE_STYLES[plan];
  const progress = getPlanProgressPercent(daysRemaining, plan);
  const limitLabel =
    agentsLimit >= 999 ? `${agentsUsed} ботов` : `Использовано ${agentsUsed} из ${agentsLimit} ботов`;

  return (
    <section className="grid gap-4 xl:grid-cols-[1.4fr_1fr_1fr]">
      <article className="relative overflow-hidden rounded-2xl border border-zinc-800/80 bg-gradient-to-br from-[#0c0c0e] via-[#121214] to-black p-6">
        <div className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-500/10 ring-1 ring-violet-500/25">
            <Building2 className="h-7 w-7 text-violet-400" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-600">
              Рабочая группа
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-zinc-50">
              MP.AI Production Console
            </h1>
            <p className="mt-2 truncate text-sm text-zinc-400">{companyName}</p>
            <p className="mt-1 font-mono text-[11px] text-zinc-600">
              ID: {workspaceId.slice(0, 8)}…
            </p>
          </div>
        </div>
      </article>

      <article className="rounded-2xl border border-zinc-800/80 bg-[#121214] p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-600">
              Баланс аккаунта
            </p>
            <p className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">
              {formatBillingCurrency(balance, currency)}
            </p>
            <p className="mt-1 text-xs text-zinc-500">Live Wallet · KZT billing</p>
          </div>
          <button
            type="button"
            onClick={onTopUpClick}
            aria-label="Пополнить баланс"
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-glow-purple transition hover:from-violet-500 hover:to-indigo-500"
          >
            <Plus className="h-5 w-5" />
          </button>
        </div>
        <div className="mt-4 flex items-center gap-2 text-xs text-zinc-500">
          <Wallet className="h-3.5 w-3.5 text-violet-400" />
          Мгновенное пополнение через симуляцию платежа
        </div>
      </article>

      <article
        className={cn(
          "rounded-2xl border bg-[#121214] p-6",
          planStyles.border,
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-600">
              Подписка
            </p>
            <div className="mt-2 flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1",
                  planStyles.badge,
                )}
              >
                <Crown className="h-3.5 w-3.5" />
                {PLAN_LABELS[plan]}
              </span>
            </div>
            <p className={cn("mt-3 text-sm font-medium", planStyles.accent)}>{limitLabel}</p>
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-2 flex items-center justify-between text-[11px] text-zinc-500">
            <span>
              {daysRemaining !== null
                ? `Осталось ${daysRemaining} дн.`
                : "Бессрочный период"}
            </span>
            <span>{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-900 ring-1 ring-zinc-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-600 to-indigo-500 transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </article>
    </section>
  );
}
