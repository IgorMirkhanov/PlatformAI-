"use client";

import Link from "next/link";
import { Sparkles, Wallet } from "lucide-react";

import { formatBillingCurrency } from "@/lib/billing-utils";
import { useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY } from "@/types/billing";

export function BillingSidebarWidget() {
  const billing = useBotStore((state) => state.billing);
  const billingLoading = useBotStore((state) => state.billingLoading);

  const balance = billing?.balance ?? 0;
  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const threshold = billing?.low_balance_threshold_kzt ?? 2500;
  const isLow =
    Boolean(billing?.is_low_balance) ||
    (typeof billing?.balance === "number" && billing.balance < threshold);
  const isCritical = typeof billing?.balance === "number" && billing.balance <= 0;

  return (
    <Link
      href="/billing"
      className={
        isCritical
          ? "group relative block overflow-hidden rounded-xl border border-rose-500/40 bg-gradient-to-br from-rose-950/40 via-zinc-950/60 to-black p-4 transition hover:border-rose-400/60"
          : isLow
            ? "group relative block overflow-hidden rounded-xl border border-amber-500/35 bg-gradient-to-br from-amber-950/35 via-zinc-950/60 to-black p-4 transition hover:border-amber-400/50"
            : "group relative block overflow-hidden rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-950/30 via-zinc-950/60 to-black p-4 transition hover:border-violet-500/40 hover:shadow-glow-purple"
      }
    >
      <div
        className={
          isCritical
            ? "pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-rose-500/20 blur-2xl"
            : isLow
              ? "pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-amber-500/20 blur-2xl"
              : "pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-violet-500/20 blur-2xl transition group-hover:bg-violet-500/25"
        }
      />

      <div className="relative flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Wallet
            className={
              isCritical ? "h-4 w-4 text-rose-400" : isLow ? "h-4 w-4 text-amber-400" : "h-4 w-4 text-violet-400"
            }
          />
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
            Баланс
          </span>
        </div>
        {(isLow || isCritical) && (
          <span
            className={
              isCritical
                ? "rounded-md bg-rose-500/20 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-rose-200"
                : "rounded-md bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-200"
            }
          >
            {isCritical ? "Пусто" : "Мало"}
          </span>
        )}
        {!isLow && !isCritical ? <Sparkles className="h-3.5 w-3.5 text-violet-400/70" /> : null}
      </div>

      <div className="relative mt-3">
        <p
          className={
            isCritical
              ? "text-xs font-bold uppercase tracking-wider text-rose-300"
              : isLow
                ? "text-xs font-bold uppercase tracking-wider text-amber-300"
                : "text-xs font-bold uppercase tracking-wider text-violet-300"
          }
        >
          Организация
        </p>
        <p className="mt-1 text-2xl font-semibold tracking-tight text-white">
          {billingLoading ? "…" : formatBillingCurrency(balance, currency)}
        </p>
        <p className="mt-2 text-[10px] text-zinc-500">
          {isCritical
            ? "Пополните кошелёк — ИИ может не отвечать"
            : isLow
              ? `Ниже порога ${formatBillingCurrency(threshold, currency)}`
              : "Кошелёк организации"}
        </p>
      </div>
    </Link>
  );
}
