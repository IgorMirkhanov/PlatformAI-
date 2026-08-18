"use client";

import { Bot } from "lucide-react";

import { formatPlanExpiryLabel, formatRenewalDate, getPlanProgressPercent } from "@/lib/billing-utils";
import type { BillingStatusResponse } from "@/types/billing";

interface BillingAgentsPanelProps {
  billing: BillingStatusResponse;
  activeAgentsCount: number;
}

export function BillingAgentsPanel({ billing, activeAgentsCount }: BillingAgentsPanelProps) {
  const progress = getPlanProgressPercent(billing.days_remaining, billing.plan_name);
  const renewalDate = formatRenewalDate(billing.expires_at);

  return (
    <section className="rounded-2xl border border-zinc-800/80 bg-zinc-950/60 p-6 backdrop-blur-xl">
      <div className="mb-5 flex items-center gap-2">
        <Bot className="h-4 w-4 text-violet-400" />
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Агенты в подписке</h3>
          <p className="text-xs text-zinc-500">Лимиты активных AI-агентов по текущему тарифу</p>
        </div>
      </div>

      <div className="rounded-xl border border-violet-500/15 bg-violet-500/5 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-zinc-500">Активные агенты</p>
            <p className="mt-1 text-2xl font-semibold text-white">
              {activeAgentsCount}
              <span className="text-base font-normal text-zinc-500">
                {" "}
                / {billing.active_agents_limit >= 999 ? "∞" : billing.active_agents_limit}
              </span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wide text-zinc-500">Подписка</p>
            <p className="mt-1 text-sm font-semibold text-violet-200">{billing.plan_name}</p>
            <p className="mt-1 text-xs text-zinc-500">
              {formatPlanExpiryLabel(billing.expires_at, billing.days_remaining)}
            </p>
          </div>
        </div>

        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-zinc-800/80">
          <div
            className="h-full rounded-full bg-gradient-to-r from-violet-600 to-indigo-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        {renewalDate ? (
          <p className="mt-3 text-xs text-zinc-500">Подписка будет продлена {renewalDate}</p>
        ) : null}
      </div>
    </section>
  );
}
