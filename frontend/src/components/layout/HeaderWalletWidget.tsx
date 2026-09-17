"use client";

import { useEffect, useState } from "react";
import { Loader2, Plus, Wallet } from "lucide-react";

import { BalanceTopUpModal } from "@/components/billing/ManualDepositWidget";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { canAccessBilling } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY } from "@/types/billing";

export function HeaderWalletWidget() {
  const currentUser = useBotStore((state) => state.currentUser);
  const billing = useBotStore((state) => state.billing);
  const billingLoading = useBotStore((state) => state.billingLoading);
  const loadBilling = useBotStore((state) => state.loadBilling);

  const [depositOpen, setDepositOpen] = useState(false);

  const showWidget = canAccessBilling(currentUser?.role);

  useEffect(() => {
    if (showWidget) {
      void loadBilling();
    }
  }, [loadBilling, showWidget]);

  if (!showWidget) {
    return null;
  }

  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const balance = billing?.balance ?? 0;
  const threshold = billing?.low_balance_threshold_kzt ?? 2500;
  const isLow =
    Boolean(billing?.is_low_balance) ||
    (typeof billing?.balance === "number" && billing.balance < threshold);
  const isCritical = typeof billing?.balance === "number" && billing.balance <= 0;
  const balanceLabel = formatBillingCurrency(balance, currency);

  return (
    <>
      <div
        className={cn(
          "inline-flex items-center gap-1 rounded-xl border bg-zinc-950/70",
          "shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition",
          isCritical
            ? "border-rose-500/50 hover:border-rose-400/70 hover:bg-rose-950/40"
            : isLow
              ? "border-amber-500/40 hover:border-amber-400/60 hover:bg-amber-950/30"
              : "border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-900/80",
        )}
        title={
          isCritical
            ? "Баланс исчерпан — пополните кошелёк"
            : isLow
              ? "Низкий баланс — рекомендуется пополнение"
              : undefined
        }
      >
        <div className="flex items-center gap-2 px-2.5 py-1.5 sm:px-3 sm:py-2">
          <div
            className={cn(
              "relative flex h-7 w-7 items-center justify-center rounded-lg ring-1",
              isCritical
                ? "bg-rose-500/15 ring-rose-500/40"
                : isLow
                  ? "bg-amber-500/15 ring-amber-500/35"
                  : "bg-violet-500/10 ring-violet-500/25",
            )}
          >
            <Wallet
              className={cn(
                "h-3.5 w-3.5",
                isCritical
                  ? "text-rose-300"
                  : isLow
                    ? "text-amber-300"
                    : "text-violet-400 drop-shadow-[0_0_8px_rgba(139,92,246,0.55)]",
              )}
            />
            {(isLow || isCritical) && (
              <span
                className={cn(
                  "absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full ring-2 ring-zinc-950",
                  isCritical ? "bg-rose-400" : "bg-amber-400",
                )}
              />
            )}
          </div>
          {billingLoading && !billing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500" />
          ) : (
            <span
              className={cn(
                "max-w-[7.5rem] truncate text-xs font-semibold tabular-nums sm:max-w-none sm:text-sm",
                isCritical ? "text-rose-200" : isLow ? "text-amber-100" : "text-zinc-100",
              )}
            >
              {balanceLabel}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={() => setDepositOpen(true)}
          aria-label="Пополнить баланс"
          className={cn(
            "mr-1 inline-flex h-7 w-7 items-center justify-center rounded-lg",
            "bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-glow-purple",
            "transition hover:from-violet-500 hover:to-indigo-500 active:scale-95",
          )}
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
      </div>

      <BalanceTopUpModal
        open={depositOpen}
        onClose={() => {
          setDepositOpen(false);
          void loadBilling();
        }}
      />
    </>
  );
}
