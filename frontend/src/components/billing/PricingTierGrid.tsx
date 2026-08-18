"use client";

import { Check, Crown, Loader2, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  PLAN_BADGE_STYLES,
  PRICING_TIERS,
  type SubscriptionPlanName,
} from "@/types/billing";

interface PricingTierGridProps {
  currentPlan: SubscriptionPlanName;
  onSelectPlan: (plan: SubscriptionPlanName) => Promise<void>;
  loading?: boolean;
  loadingPlan?: SubscriptionPlanName | null;
}

export function PricingTierGrid({
  currentPlan,
  onSelectPlan,
  loading = false,
  loadingPlan = null,
}: PricingTierGridProps) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      {PRICING_TIERS.map((tier) => {
        const isCurrent = tier.id === currentPlan;
        const isLoadingThis = loading && loadingPlan === tier.id;
        const styles = PLAN_BADGE_STYLES[tier.id];

        return (
          <article
            key={tier.id}
            className={cn(
              "relative flex min-h-[420px] flex-col overflow-hidden rounded-2xl border bg-zinc-950/60 p-6 backdrop-blur-xl transition duration-300",
              isCurrent
                ? "border-violet-500/40 shadow-[0_0_32px_rgba(139,92,246,0.12)]"
                : tier.highlighted
                  ? "border-violet-500/25 hover:border-violet-500/40"
                  : "border-zinc-800/80 hover:border-zinc-700/80",
            )}
          >
            {tier.highlighted ? (
              <span className="absolute right-5 top-5 inline-flex items-center gap-1 rounded-full bg-violet-600 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-white">
                <Sparkles className="h-3 w-3" />
                {tier.badgeLabel ?? "Популярный"}
              </span>
            ) : null}

            {isCurrent ? (
              <span className="absolute left-5 top-5 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-300 ring-1 ring-emerald-500/25">
                Текущий тариф
              </span>
            ) : null}

            <div className="mt-8">
              <div className="flex items-center gap-2">
                {tier.id === "ENTERPRISE" ? (
                  <Crown className={cn("h-4 w-4", styles.accent)} />
                ) : null}
                <p className={cn("text-sm font-semibold uppercase tracking-[0.14em]", styles.accent)}>
                  {tier.nameRu}
                </p>
              </div>
              <p className="mt-3 text-3xl font-bold text-white">{tier.priceLabel}</p>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">{tier.description}</p>
            </div>

            <div className="mt-6 space-y-3 border-t border-zinc-800/80 pt-5">
              {tier.features.map((feature) => (
                <div key={feature.id} className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    <span className="text-sm text-zinc-300">{feature.label}</span>
                  </div>
                  <span className="text-right text-sm font-medium text-zinc-100">{feature.value}</span>
                </div>
              ))}
            </div>

            <div className="mt-auto pt-6">
              {isCurrent ? (
                <div
                  className={cn(
                    "inline-flex w-full items-center justify-center rounded-xl px-4 py-3 text-sm font-semibold ring-1",
                    styles.badge,
                  )}
                >
                  Текущий тариф
                </div>
              ) : (
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => void onSelectPlan(tier.id)}
                  className={cn(
                    "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold transition disabled:opacity-60",
                    tier.highlighted
                      ? "bg-violet-600 text-white hover:bg-violet-500 shadow-glow-purple"
                      : "border border-zinc-700 bg-zinc-900/70 text-zinc-100 hover:border-zinc-600 hover:bg-zinc-800/80",
                  )}
                >
                  {isLoadingThis ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Перейти на тариф
                </button>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}
