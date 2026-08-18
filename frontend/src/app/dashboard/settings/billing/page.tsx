"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  CreditCard,
  Loader2,
  RefreshCw,
  Sparkles,
  Wallet,
} from "lucide-react";

import { SettingsSectionNav } from "@/components/settings/SettingsSectionNav";
import { useToast } from "@/hooks/useToast";
import {
  getCreditTransactions,
  getWalletBalance,
  type BillingTransaction,
  type WalletBalanceResponse,
} from "@/lib/billing/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { canManageBilling } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY } from "@/types/billing";

const PAGE_SIZE = 15;

function formatSignedAmount(amount: number, currency: string): string {
  const sign = amount < 0 ? "−" : amount > 0 ? "+" : "";
  const abs = Math.abs(amount);
  if (currency === "CREDITS") {
    return `${sign}${abs.toLocaleString("ru-RU")} кр.`;
  }
  return `${sign}${formatBillingCurrency(abs, DEFAULT_BILLING_CURRENCY)}`;
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso.slice(0, 16);
  }
}

export default function DashboardBillingSettingsPage() {
  const currentUser = useBotStore((s) => s.currentUser);
  const loadCurrentUser = useBotStore((s) => s.loadCurrentUser);
  const { showToast } = useToast();
  const allowed = canManageBilling(currentUser?.role);

  const [wallet, setWallet] = useState<WalletBalanceResponse | null>(null);
  const [walletLoading, setWalletLoading] = useState(true);
  const [transactions, setTransactions] = useState<BillingTransaction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [txLoading, setTxLoading] = useState(true);
  const [upgradeOpen, setUpgradeOpen] = useState(false);

  const loadWallet = useCallback(async () => {
    setWalletLoading(true);
    try {
      const data = await getWalletBalance();
      setWallet(data);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить баланс кошелька."), "error");
    } finally {
      setWalletLoading(false);
    }
  }, [showToast]);

  const loadTransactions = useCallback(async () => {
    setTxLoading(true);
    try {
      const data = await getCreditTransactions(page, PAGE_SIZE);
      setTransactions(data.transactions);
      setTotal(data.total);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить транзакции."), "error");
    } finally {
      setTxLoading(false);
    }
  }, [page, showToast]);

  useEffect(() => {
    void loadCurrentUser();
  }, [loadCurrentUser]);

  useEffect(() => {
    if (!allowed) return;
    void loadWallet();
  }, [allowed, loadWallet]);

  useEffect(() => {
    if (!allowed) return;
    void loadTransactions();
  }, [allowed, loadTransactions]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  if (!allowed) {
    return (
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 lg:px-8">
        <SettingsSectionNav role={currentUser?.role} />
        <div className="rounded-2xl border border-zinc-800 bg-zinc-950/50 px-5 py-8 text-center">
          <CreditCard className="mx-auto h-8 w-8 text-zinc-600" />
          <h1 className="mt-3 text-lg font-semibold text-zinc-200">Биллинг недоступен</h1>
          <p className="mt-2 text-sm text-zinc-500">
            Раздел доступен только OWNER и ADMIN (`can_manage_billing`).
          </p>
          <Link
            href="/dashboard/settings/team"
            className="mt-4 inline-flex text-sm text-violet-400 hover:text-violet-300"
          >
            Вернуться к команде
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 lg:px-8">
      <SettingsSectionNav role={currentUser?.role} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
            Настройки организации
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-zinc-50">Биллинг и кошелёк</h1>
          <p className="mt-2 text-sm text-zinc-500">
            Баланс кредитов организации и журнал операций.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              void loadWallet();
              void loadTransactions();
            }}
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 px-3 py-2 text-xs font-semibold text-zinc-300 hover:border-zinc-700"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Обновить
          </button>
          <button
            type="button"
            onClick={() => setUpgradeOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white"
          >
            <Sparkles className="h-4 w-4" />
            Пополнить баланс
          </button>
        </div>
      </header>

      <section className="rounded-2xl border border-violet-500/20 bg-gradient-to-br from-violet-950/40 via-[#0d0d0f] to-indigo-950/30 p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-violet-500/15 p-3 ring-1 ring-violet-500/30">
            <Wallet className="h-6 w-6 text-violet-300" />
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
              Баланс кошелька
            </p>
            {walletLoading ? (
              <Loader2 className="mt-2 h-6 w-6 animate-spin text-violet-400" />
            ) : (
              <p className="mt-1 text-4xl font-semibold tracking-tight text-zinc-50">
                {(wallet?.balance ?? 0).toLocaleString("ru-RU")}
                <span className="ml-2 text-base font-medium text-zinc-400">
                  {wallet?.currency === "CREDITS" ? "кредитов" : wallet?.currency}
                </span>
              </p>
            )}
          </div>
        </div>
        {wallet?.plan_balance_kzt != null ? (
          <p className="mt-4 text-sm text-zinc-400">
            Подписочный баланс:{" "}
            <span className="font-medium text-zinc-200">
              {formatBillingCurrency(wallet.plan_balance_kzt, DEFAULT_BILLING_CURRENCY)}
            </span>
          </p>
        ) : null}
      </section>

      <section className="rounded-2xl border border-zinc-800/80 bg-[#0d0d0f]/90 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Журнал транзакций</h2>
            <p className="text-xs text-zinc-500">Списания и пополнения · {total} записей</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1 || txLoading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2 py-1 text-xs text-zinc-300 disabled:opacity-40"
            >
              <ArrowLeft className="h-3 w-3" />
              Назад
            </button>
            <span className="text-xs text-zinc-500">
              {page} / {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages || txLoading}
              onClick={() => setPage((p) => p + 1)}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2 py-1 text-xs text-zinc-300 disabled:opacity-40"
            >
              Вперёд
              <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        </div>

        {txLoading ? (
          <div className="flex min-h-[180px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
          </div>
        ) : transactions.length === 0 ? (
          <p className="py-10 text-center text-sm text-zinc-500">Пока нет операций.</p>
        ) : (
          <div className="max-h-[480px] overflow-auto rounded-xl border border-zinc-800/80">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 bg-zinc-950 text-[11px] uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Дата</th>
                  <th className="px-4 py-3 font-medium">Тип</th>
                  <th className="px-4 py-3 font-medium">Сумма</th>
                  <th className="px-4 py-3 font-medium">Reference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/80">
                {transactions.map((tx) => (
                  <tr key={tx.id} className="bg-zinc-950/20">
                    <td className="whitespace-nowrap px-4 py-3 text-zinc-400">
                      {formatDate(tx.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-md bg-zinc-900 px-2 py-0.5 text-[11px] font-medium text-zinc-300 ring-1 ring-zinc-700/60">
                        {tx.transaction_type}
                      </span>
                      {tx.description ? (
                        <p className="mt-1 max-w-xs truncate text-xs text-zinc-500">
                          {tx.description}
                        </p>
                      ) : null}
                    </td>
                    <td
                      className={cn(
                        "px-4 py-3 font-medium tabular-nums",
                        tx.amount < 0 ? "text-rose-300" : "text-emerald-300",
                      )}
                    >
                      {formatSignedAmount(tx.amount, tx.currency)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                      {tx.reference_id ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-xs text-zinc-600">
        Расширенные подписки и Stripe Checkout:{" "}
        <Link href="/dashboard/billing" className="text-violet-400 hover:text-violet-300">
          /dashboard/billing
        </Link>
      </p>

      {upgradeOpen ? (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm"
          onClick={() => setUpgradeOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold text-zinc-50">Пополнение баланса</h2>
            <p className="mt-2 text-sm text-zinc-400">
              Для пополнения кошелька и смены тарифа откройте полный биллинг-кабинет с Stripe
              Checkout.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setUpgradeOpen(false)}
                className="rounded-xl border border-zinc-800 px-4 py-2 text-sm text-zinc-300"
              >
                Закрыть
              </button>
              <Link
                href="/dashboard/billing"
                className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white"
              >
                <CreditCard className="h-4 w-4" />
                Открыть биллинг
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
