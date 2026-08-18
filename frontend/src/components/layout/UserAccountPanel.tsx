"use client";

import Link from "next/link";
import { Plus, Sparkles, UserCircle2 } from "lucide-react";

import { formatBillingCurrency } from "@/lib/billing-utils";
import { canAccessBilling } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY, PLAN_BADGE_STYLES, type SubscriptionPlanName } from "@/types/billing";

export function UserAccountPanel() {
  const billing = useBotStore((state) => state.billing);
  const billingLoading = useBotStore((state) => state.billingLoading);
  const currentUser = useBotStore((state) => state.currentUser);

  const plan = billing?.plan_name ?? "FREE";
  const balance = billing?.balance ?? 0;
  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const planStyles = PLAN_BADGE_STYLES[plan as SubscriptionPlanName];
  const showBilling = canAccessBilling(currentUser?.role);

  return (
    <div className="moonai-account-panel">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600/30 to-indigo-600/10 ring-1 ring-violet-500/30">
          <UserCircle2 className="h-6 w-6 text-violet-300" />
        </div>
        <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-zinc-100">
              {currentUser?.full_name || "MP.AI Production Console"}
            </p>
            <p className="text-[11px] text-zinc-500">{currentUser?.email || "admin@mp.ai"}</p>
          <span
            className={cn(
              "mt-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1",
              planStyles.badge,
            )}
          >
            <Sparkles className="h-3 w-3" />
            {plan}
          </span>
        </div>
      </div>

      {showBilling && (
        <div className="mt-4 rounded-xl border border-zinc-800/80 bg-black/30 p-3">
          <div className="flex items-center justify-between gap-2">
            <Link href="/billing" className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                Баланс аккаунта
              </p>
              <p className="mt-1 text-xl font-semibold tracking-tight text-white">
                {billingLoading ? "…" : formatBillingCurrency(balance, currency)}
              </p>
            </Link>
            <Link
              href="/billing"
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-violet-600 text-white transition hover:bg-violet-500 hover:shadow-glow-purple"
              aria-label="Открыть биллинг и подписки"
            >
              <Plus className="h-4 w-4" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
