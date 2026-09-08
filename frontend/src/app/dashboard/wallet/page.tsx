"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Coins, CreditCard, Activity } from "lucide-react";

import { fetchTokenUsageByBot, fetchTokenWallet, type TokenWalletOverview, type TokenUsageByBot } from "@/lib/api";
import { canAccessBilling } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";

export default function WalletPage() {
  const currentUser = useBotStore((s) => s.currentUser);
  const loadCurrentUser = useBotStore((s) => s.loadCurrentUser);
  const allowed = canAccessBilling(currentUser?.role);
  const [wallet, setWallet] = useState<TokenWalletOverview | null>(null);
  const [usage, setUsage] = useState<TokenUsageByBot | null>(null);
  const [days, setDays] = useState(7);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [w, u] = await Promise.all([fetchTokenWallet(), fetchTokenUsageByBot(days)]);
      setWallet(w);
      setUsage(u);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось загрузить кошелёк.");
    }
  }, [days]);

  useEffect(() => {
    if (!currentUser) void loadCurrentUser();
  }, [currentUser, loadCurrentUser]);

  useEffect(() => {
    if (!allowed) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    return () => window.clearInterval(timer);
  }, [allowed, refresh]);

  if (!currentUser) {
    return (
      <div data-testid="wallet-loading" className="px-4 py-10 text-sm text-[var(--canvas-muted)]">
        Загрузка…
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="px-4 py-10 text-sm text-[var(--canvas-muted)]">
        Недостаточно прав для просмотра кошелька.
      </div>
    );
  }

  const blocked = wallet?.status === "blocked";

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8 lg:px-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--canvas-fg)]">
          Кошелёк организации
        </h1>
        <p className="mt-1 text-sm text-[var(--canvas-muted)]">
          Баланс токенов и списания по агентам. Обновление каждые 10 секунд.
        </p>
      </div>

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      {blocked ? (
        <div
          data-testid="wallet-page-blocked-banner"
          className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100"
        >
          Генерация ИИ остановлена: баланс исчерпан.{" "}
          <Link href="/dashboard/billing" className="font-semibold underline">
            Пополнить
          </Link>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          {
            label: "Токены",
            value: wallet?.balance_tokens ?? "—",
            icon: Coins,
            testId: "wallet-balance",
          },
          {
            label: "Статус",
            value: wallet?.status ?? "—",
            icon: Activity,
            testId: "wallet-status",
          },
          {
            label: "Кредиты",
            value: wallet?.credit_balance ?? "—",
            icon: CreditCard,
            testId: undefined,
          },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className="flex items-center gap-4 rounded-2xl border border-[var(--canvas-border)] bg-[var(--card)] px-5 py-4 shadow-soft"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
                <Icon className="h-5 w-5 text-violet-400" />
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">{card.label}</p>
                <p
                  data-testid={card.testId}
                  className="mt-1 text-2xl font-semibold tabular-nums text-[var(--canvas-fg)]"
                >
                  {card.value}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex gap-2">
        {[7, 30].map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setDays(value)}
            className={cn(
              "rounded-xl border px-3 py-1.5 text-xs font-semibold transition",
              days === value
                ? "border-violet-500/40 bg-violet-500/10 text-violet-300"
                : "border-[var(--canvas-border)] text-[var(--canvas-muted)] hover:text-[var(--canvas-fg)]",
            )}
          >
            {value} дней
          </button>
        ))}
      </div>

      <section className="moonai-panel !p-0 overflow-hidden">
        <div className="border-b border-[var(--canvas-border)] px-5 py-3 text-xs font-semibold uppercase tracking-wide text-[var(--canvas-muted)]">
          Расход по ботам
        </div>
        <ul className="divide-y divide-[var(--canvas-border)] text-sm">
          {(usage?.items ?? []).length === 0 ? (
            <li className="px-5 py-4 text-[var(--canvas-muted)]">Нет списаний за период.</li>
          ) : (
            usage?.items.map((row) => (
              <li key={row.bot_id ?? "none"} className="flex justify-between px-5 py-3">
                <span className="text-[var(--canvas-fg)]">{row.bot_id ?? "без бота"}</span>
                <span className="tabular-nums text-[var(--canvas-fg)]">{row.amount_tokens}</span>
              </li>
            ))
          )}
        </ul>
      </section>

      <section className="moonai-panel !p-0 overflow-hidden">
        <div className="border-b border-[var(--canvas-border)] px-5 py-3 text-xs font-semibold uppercase tracking-wide text-[var(--canvas-muted)]">
          Последние операции
        </div>
        <ul className="divide-y divide-[var(--canvas-border)] text-sm">
          {(wallet?.transactions ?? []).length === 0 ? (
            <li className="px-5 py-4 text-[var(--canvas-muted)]">Операций пока нет.</li>
          ) : (
            (wallet?.transactions ?? []).map((tx) => (
              <li key={tx.id} className="flex justify-between px-5 py-3">
                <span className="text-[var(--canvas-muted)]">
                  {tx.tx_type} {tx.model_used ? `· ${tx.model_used}` : ""}
                </span>
                <span className="tabular-nums text-[var(--canvas-fg)]">{tx.amount_tokens}</span>
              </li>
            ))
          )}
        </ul>
      </section>
    </div>
  );
}
