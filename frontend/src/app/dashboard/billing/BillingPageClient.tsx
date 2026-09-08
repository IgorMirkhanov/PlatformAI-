"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CreditCard, Loader2, Sparkles, Wallet } from "lucide-react";

import { BalanceTopUpModal } from "@/components/billing/ManualDepositWidget";
import {
  TransactionLedger,
  type TransactionTypeFilter,
} from "@/components/billing/TransactionLedger";
import { useToast } from "@/hooks/useToast";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { fetchBillingTransactions, openBillingPortal } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useImpersonation } from "@/lib/hooks/useImpersonation";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { BillingTransaction } from "@/types/billing";
import { DEFAULT_BILLING_CURRENCY } from "@/types/billing";

const PAGE_SIZE = 10;

export default function BillingPageClient() {
  const searchParams = useSearchParams();
  const { showToast } = useToast();
  const billing = useBotStore((state) => state.billing);
  const billingLoading = useBotStore((state) => state.billingLoading);
  const loadBilling = useBotStore((state) => state.loadBilling);
  const { isImpersonating } = useImpersonation();

  const [topUpOpen, setTopUpOpen] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);

  const [transactions, setTransactions] = useState<BillingTransaction[]>([]);
  const [transactionsTotal, setTransactionsTotal] = useState(0);
  const [transactionsLoading, setTransactionsLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState<TransactionTypeFilter>("all");
  const [page, setPage] = useState(1);

  const loadTransactions = useCallback(async () => {
    setTransactionsLoading(true);
    try {
      const response = await fetchBillingTransactions({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        typeGroup: typeFilter === "all" ? "all" : typeFilter,
      });
      setTransactions(response.transactions);
      setTransactionsTotal(response.total);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить историю операций."), "error");
    } finally {
      setTransactionsLoading(false);
    }
  }, [page, showToast, typeFilter]);

  useEffect(() => {
    void loadBilling();
  }, [loadBilling]);

  useEffect(() => {
    void loadTransactions();
  }, [loadTransactions]);

  useEffect(() => {
    const status = searchParams.get("status");
    const checkout = searchParams.get("checkout");
    const isSuccess = status === "success" || checkout === "success";
    const isCancel = status === "cancel" || checkout === "cancel";

    if (isSuccess) {
      showToast("Платеж успешно обработан, баланс пополнен!", "success");
      void loadBilling();
      void loadTransactions();
    } else if (isCancel) {
      showToast("Оплата отменена.", "error");
    }
  }, [loadBilling, loadTransactions, searchParams, showToast]);

  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const balance = billing?.balance ?? 0;

  const handlePortal = useCallback(async () => {
    if (isImpersonating) {
      showToast("Billing actions are blocked during impersonation.", "error");
      return;
    }
    setPortalLoading(true);
    try {
      const result = await openBillingPortal();
      if (!result.url) {
        throw new Error("Stripe did not return a Portal URL.");
      }
      window.location.assign(result.url);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to open Stripe Portal."), "error");
      setPortalLoading(false);
    }
  }, [isImpersonating, showToast]);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-8 px-4 py-8 lg:px-0">
      <header className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
          Billing
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Wallet & payments</h1>
        <p className="max-w-xl text-sm text-zinc-500">
          Пополнение баланса картой или безналичным переводом. Средства используются для LLM и
          платформенных операций.
        </p>
      </header>

      {billing?.is_low_balance ? (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          Баланс ниже {formatBillingCurrency(billing.low_balance_threshold_kzt ?? 2500, "KZT")}.
          Рекомендуем пополнить кошелёк.
        </div>
      ) : null}

      <section className="relative overflow-hidden rounded-3xl border border-zinc-800/80 bg-gradient-to-br from-zinc-950 via-zinc-900/80 to-black p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
        <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-amber-500/10 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
              <Wallet className="h-3.5 w-3.5 text-amber-300" />
              Current wallet balance
            </div>
            <p className="mt-3 text-4xl font-semibold tracking-tight text-zinc-50 md:text-5xl">
              {billingLoading ? "…" : formatBillingCurrency(balance, currency)}
            </p>
            <p className="mt-2 text-sm text-zinc-500">
              Основной счёт организации в тенге (₸).
            </p>
          </div>
          <div className="rounded-2xl border border-zinc-800 bg-black/40 px-4 py-3 text-right">
            <p className="text-[10px] uppercase tracking-wide text-zinc-500">Организация</p>
            <p className="mt-1 text-lg font-semibold text-zinc-100">Кошелёк</p>
            <p className="mt-1 text-xs text-zinc-500">Подписка оформляется на каждого агента</p>
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-zinc-800/80 bg-zinc-950/70 p-6">
        <div className="mb-5 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-amber-300" />
          <h2 className="text-lg font-medium text-zinc-50">Top up</h2>
        </div>

        {isImpersonating ? (
          <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            Impersonation mode: billing top-up is disabled.
          </div>
        ) : null}

        <p className="mb-5 text-sm text-zinc-500">
          Выберите способ: мгновенное пополнение картой или ручной перевод по реквизитам с загрузкой
          чека.
        </p>

        <button
          type="button"
          onClick={() => setTopUpOpen(true)}
          disabled={isImpersonating}
          className={cn(
            "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 py-3 text-sm font-semibold text-zinc-950 transition hover:bg-amber-300 disabled:opacity-60",
          )}
        >
          <CreditCard className="h-4 w-4" />
          Пополнить баланс
        </button>
      </section>

      <TransactionLedger
        transactions={transactions}
        total={transactionsTotal}
        currency={currency}
        loading={transactionsLoading}
        pageSize={PAGE_SIZE}
        typeFilter={typeFilter}
        onTypeFilterChange={(value) => {
          setTypeFilter(value);
          setPage(1);
        }}
        page={page}
        onPageChange={setPage}
      />

      <section className="rounded-3xl border border-zinc-800/80 bg-zinc-950/70 p-6">
        <div className="mb-3 flex items-center gap-2">
          <CreditCard className="h-4 w-4 text-zinc-300" />
          <h2 className="text-lg font-medium text-zinc-50">Payment methods</h2>
        </div>
        <p className="mb-5 text-sm text-zinc-500">
          Update saved cards, download invoices, and manage billing details in the Stripe Customer
          Portal (when Stripe is configured).
        </p>
        <button
          type="button"
          onClick={() => void handlePortal()}
          disabled={portalLoading || isImpersonating}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/70 px-4 py-3 text-sm font-semibold text-zinc-100 transition hover:border-zinc-500 hover:bg-zinc-900 disabled:opacity-60"
        >
          {portalLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Opening portal…
            </>
          ) : (
            "Manage Cards & Invoices"
          )}
        </button>
      </section>

      <BalanceTopUpModal
        open={topUpOpen}
        onClose={() => {
          setTopUpOpen(false);
          void loadBilling();
          void loadTransactions();
        }}
      />
    </div>
  );
}
