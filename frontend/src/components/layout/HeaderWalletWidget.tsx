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
  const balanceLabel = formatBillingCurrency(billing?.balance ?? 0, currency);

  return (
    <>
      <div
        className={cn(
          "inline-flex items-center gap-1 rounded-xl border border-zinc-800/80 bg-zinc-950/70",
          "shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition hover:border-zinc-700 hover:bg-zinc-900/80",
        )}
      >
        <div className="flex items-center gap-2 px-2.5 py-1.5 sm:px-3 sm:py-2">
          <div className="relative flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10 ring-1 ring-violet-500/25">
            <Wallet className="h-3.5 w-3.5 text-violet-400 drop-shadow-[0_0_8px_rgba(139,92,246,0.55)]" />
          </div>
          {billingLoading && !billing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500" />
          ) : (
            <span className="max-w-[7.5rem] truncate text-xs font-semibold tabular-nums text-zinc-100 sm:max-w-none sm:text-sm">
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
