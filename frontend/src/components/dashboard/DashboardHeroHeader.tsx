"use client";

import { Bot, Building2, Plus, Wallet } from "lucide-react";

import { formatBillingCurrency } from "@/lib/billing-utils";
import type { BillingCurrency } from "@/types/billing";

interface DashboardHeroHeaderProps {
  companyName: string;
  workspaceId: string;
  balance: number;
  currency: BillingCurrency;
  agentsUsed: number;
  subscribedAgents: number;
  onTopUpClick: () => void;
}

export function DashboardHeroHeader({
  companyName,
  workspaceId,
  balance,
  currency,
  agentsUsed,
  subscribedAgents,
  onTopUpClick,
}: DashboardHeroHeaderProps) {
  const progress =
    agentsUsed <= 0 ? 0 : Math.min(100, Math.round((subscribedAgents / agentsUsed) * 100));

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
          Пополнение картой через Stripe / TipTop Pay
        </div>
      </article>

      <article className="rounded-2xl border border-violet-500/20 bg-[#121214] p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-600">
              Подписки агентов
            </p>
            <div className="mt-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-500/10 px-2.5 py-1 text-xs font-semibold text-violet-200 ring-1 ring-violet-500/25">
                <Bot className="h-3.5 w-3.5" />
                {subscribedAgents} из {agentsUsed}
              </span>
            </div>
            <p className="mt-3 text-sm font-medium text-violet-200">
              Без подписки агент настраивается, но не отвечает в чате
            </p>
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-2 flex items-center justify-between text-[11px] text-zinc-500">
            <span>Активные подписки</span>
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
