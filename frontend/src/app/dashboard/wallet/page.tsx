"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { fetchTokenUsageByBot, fetchTokenWallet, type TokenWalletOverview, type TokenUsageByBot } from "@/lib/api";
import { canAccessBilling } from "@/lib/permissions";
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
      <div data-testid="wallet-loading" className="px-4 py-10 text-sm text-zinc-400">
        Загрузка…
      </div>
    );
  }

  if (!allowed) {
    return <div className="px-4 py-10 text-sm text-zinc-400">Недостаточно прав для просмотра кошелька.</div>;
  }

  const blocked = wallet?.status === "blocked";

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Кошелёк организации</h1>
        <p className="mt-1 text-sm text-zinc-500">Баланс токенов обновляется каждые 10 секунд.</p>
      </div>

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

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
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Токены</p>
          <p data-testid="wallet-balance" className="mt-2 text-2xl font-semibold tabular-nums text-white">
            {wallet?.balance_tokens ?? "—"}
          </p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Статус</p>
          <p data-testid="wallet-status" className="mt-2 text-2xl font-semibold text-white">{wallet?.status ?? "—"}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Кредиты</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-white">
            {wallet?.credit_balance ?? "—"}
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        {[7, 30].map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setDays(value)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${
              days === value
                ? "border-violet-500/40 bg-violet-500/10 text-violet-200"
                : "border-zinc-800 text-zinc-400"
            }`}
          >
            {value} дней
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-zinc-800">
        <div className="border-b border-zinc-800 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Расход по ботам
        </div>
        <ul className="divide-y divide-zinc-800 text-sm">
          {(usage?.items ?? []).length === 0 ? (
            <li className="px-4 py-3 text-zinc-500">Нет списаний за период.</li>
          ) : (
            usage?.items.map((row) => (
              <li key={row.bot_id ?? "none"} className="flex justify-between px-4 py-3">
                <span className="text-zinc-300">{row.bot_id ?? "без бота"}</span>
                <span className="tabular-nums text-zinc-100">{row.amount_tokens}</span>
              </li>
            ))
          )}
        </ul>
      </div>

      <div className="rounded-xl border border-zinc-800">
        <div className="border-b border-zinc-800 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Последние операции
        </div>
        <ul className="divide-y divide-zinc-800 text-sm">
          {(wallet?.transactions ?? []).map((tx) => (
            <li key={tx.id} className="flex justify-between px-4 py-3">
              <span className="text-zinc-400">
                {tx.tx_type} {tx.model_used ? `· ${tx.model_used}` : ""}
              </span>
              <span className="tabular-nums text-zinc-100">{tx.amount_tokens}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
