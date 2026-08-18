"use client";

import Link from "next/link";
import { Sparkles, Wallet } from "lucide-react";

import { formatBillingCurrency } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY, PLAN_BADGE_STYLES, type SubscriptionPlanName } from "@/types/billing";

export function BillingSidebarWidget() {
  const billing = useBotStore((state) => state.billing);
  const billingLoading = useBotStore((state) => state.billingLoading);

  const plan = billing?.plan_name ?? "FREE";
  const balance = billing?.balance ?? 0;
  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const planStyles = PLAN_BADGE_STYLES[plan as SubscriptionPlanName];

  return (
    <Link
      href="/billing"
      className="group relative block overflow-hidden rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-950/30 via-zinc-950/60 to-black p-4 transition hover:border-violet-500/40 hover:shadow-glow-purple"
    >
      <div className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-violet-500/20 blur-2xl transition group-hover:bg-violet-500/25" />

      <div className="relative flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Wallet className="h-4 w-4 text-violet-400" />
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
            Баланс
          </span>
        </div>
        <Sparkles className="h-3.5 w-3.5 text-violet-400/70" />
      </div>

      <div className="relative mt-3">
        <p className={cn("text-xs font-bold uppercase tracking-wider", planStyles.accent)}>{plan}</p>
        <p className="mt-1 text-2xl font-semibold tracking-tight text-white">
          {billingLoading ? "…" : formatBillingCurrency(balance, currency)}
        </p>
        <p className="mt-2 text-[10px] text-zinc-500">Управление подпиской</p>
      </div>
    </Link>
  );
}
