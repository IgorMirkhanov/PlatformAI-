"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

import {
  formatBillingAmountSigned,
  formatShortTransactionId,
  formatTransactionDate,
  getTransactionStatusClassName,
} from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import type {
  BillingCurrency,
  BillingTransaction,
  BillingTransactionStatus,
} from "@/types/billing";
import { TRANSACTION_STATUS_LABELS } from "@/types/billing";

export type TransactionTypeFilter = "all" | "topup" | "llm";

interface TransactionLedgerProps {
  transactions: BillingTransaction[];
  total: number;
  currency: BillingCurrency;
  loading?: boolean;
  pageSize?: number;
  /** When provided, filter/pagination is controlled by the parent (server-side). */
  typeFilter?: TransactionTypeFilter;
  onTypeFilterChange?: (value: TransactionTypeFilter) => void;
  page?: number;
  onPageChange?: (page: number) => void;
}

const CREDIT_TYPES = new Set(["TOP_UP", "BONUS", "REFUND", "MANUAL_DEPOSIT"]);

function signedAmount(tx: BillingTransaction): number {
  if (CREDIT_TYPES.has(tx.transaction_type)) {
    return Math.abs(tx.amount);
  }
  return -Math.abs(tx.amount);
}

function statusBadgeLabel(status: BillingTransactionStatus): string {
  return status;
}

export function TransactionLedger({
  transactions,
  total,
  currency,
  loading = false,
  pageSize = 10,
  typeFilter: controlledFilter,
  onTypeFilterChange,
  page: controlledPage,
  onPageChange,
}: TransactionLedgerProps) {
  const [localFilter, setLocalFilter] = useState<TransactionTypeFilter>("all");
  const [localPage, setLocalPage] = useState(1);

  const typeFilter = controlledFilter ?? localFilter;
  const page = controlledPage ?? localPage;
  const setTypeFilter = onTypeFilterChange ?? setLocalFilter;
  const setPage = onPageChange ?? setLocalPage;
  const serverDriven = Boolean(onTypeFilterChange || onPageChange);

  const filtered = useMemo(() => {
    if (serverDriven) return transactions;
    if (typeFilter === "topup") {
      return transactions.filter((tx) => CREDIT_TYPES.has(tx.transaction_type));
    }
    if (typeFilter === "llm") {
      return transactions.filter(
        (tx) =>
          tx.transaction_type === "LLM_DEDUCTION" ||
          tx.transaction_type === "SUBSCRIPTION_CHARGE",
      );
    }
    return transactions;
  }, [serverDriven, transactions, typeFilter]);

  const effectiveTotal = serverDriven ? total : filtered.length;
  const pageCount = Math.max(1, Math.ceil(effectiveTotal / pageSize));
  const safePage = Math.min(page, pageCount);
  const pageRows = serverDriven
    ? filtered
    : filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  const filters: { id: TransactionTypeFilter; label: string }[] = [
    { id: "all", label: "Все" },
    { id: "topup", label: "Top-up" },
    { id: "llm", label: "LLM Deduction" },
  ];

  return (
    <section className="overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-950/60 backdrop-blur-xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800/80 px-6 py-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">История операций</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Журнал пополнений и списаний · {effectiveTotal} записей
          </p>
        </div>
        <div className="flex gap-1 rounded-xl border border-zinc-800 bg-zinc-950/80 p-1">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                setTypeFilter(item.id);
                setPage(1);
              }}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium transition",
                typeFilter === item.id
                  ? "bg-zinc-100 text-zinc-900"
                  : "text-zinc-400 hover:text-zinc-200",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex min-h-[240px] items-center justify-center">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
            Загрузка транзакций…
          </div>
        </div>
      ) : pageRows.length === 0 ? (
        <div className="flex min-h-[240px] items-center justify-center px-6 text-sm text-zinc-500">
          Операций пока нет. Пополните баланс или активируйте тариф.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-800/80 text-[11px] uppercase tracking-[0.12em] text-zinc-500">
                  <th className="px-6 py-3 font-semibold">ID</th>
                  <th className="px-6 py-3 font-semibold">Дата</th>
                  <th className="px-6 py-3 font-semibold">Тип</th>
                  <th className="px-6 py-3 font-semibold">Сумма</th>
                  <th className="px-6 py-3 font-semibold">Описание</th>
                  <th className="px-6 py-3 font-semibold">Статус</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((transaction) => {
                  const amount = signedAmount(transaction);
                  return (
                    <tr
                      key={transaction.id}
                      className="border-b border-zinc-900/80 transition hover:bg-zinc-900/30"
                    >
                      <td className="px-6 py-4 font-mono text-xs text-zinc-400">
                        {formatShortTransactionId(transaction.id)}
                      </td>
                      <td className="px-6 py-4 text-zinc-300">
                        {formatTransactionDate(transaction.created_at)}
                      </td>
                      <td className="px-6 py-4 text-xs text-zinc-400">
                        {transaction.transaction_type}
                      </td>
                      <td
                        className={
                          amount >= 0
                            ? "px-6 py-4 font-semibold text-emerald-400"
                            : "px-6 py-4 font-semibold text-zinc-200"
                        }
                      >
                        {formatBillingAmountSigned(amount, currency)}
                      </td>
                      <td className="px-6 py-4 text-zinc-300">{transaction.description}</td>
                      <td className="px-6 py-4">
                        <span
                          title={TRANSACTION_STATUS_LABELS[transaction.status]}
                          className={`inline-flex rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${getTransactionStatusClassName(transaction.status)}`}
                        >
                          {statusBadgeLabel(transaction.status)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between border-t border-zinc-800/80 px-6 py-3">
            <p className="text-xs text-zinc-500">
              Страница {safePage} из {pageCount}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={safePage <= 1}
                onClick={() => setPage(Math.max(1, safePage - 1))}
                className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-300 transition hover:border-zinc-600 disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                Назад
              </button>
              <button
                type="button"
                disabled={safePage >= pageCount}
                onClick={() => setPage(Math.min(pageCount, safePage + 1))}
                className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-300 transition hover:border-zinc-600 disabled:opacity-40"
              >
                Вперёд
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
