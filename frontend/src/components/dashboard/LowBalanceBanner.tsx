"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, X } from "lucide-react";

import { fetchBillingStatus, fetchOrganizationUsage } from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { useBotStore } from "@/store/useBotStore";

const DISMISS_KEY = "mpai_low_balance_banner_dismissed_at";
const DISMISS_TTL_MS = 6 * 60 * 60 * 1000; // 6 hours

export function LowBalanceBanner() {
  const billing = useBotStore((s) => s.billing);
  const loadBilling = useBotStore((s) => s.loadBilling);
  const [visible, setVisible] = useState(false);
  const [balance, setBalance] = useState<number | null>(null);
  const [threshold, setThreshold] = useState(2500);

  useEffect(() => {
    let cancelled = false;

    const dismissedAt = (() => {
      try {
        const raw = window.sessionStorage.getItem(DISMISS_KEY);
        return raw ? Number(raw) : 0;
      } catch {
        return 0;
      }
    })();
    if (dismissedAt && Date.now() - dismissedAt < DISMISS_TTL_MS) {
      return;
    }

    void (async () => {
      try {
        const [status, usage] = await Promise.all([
          billing ?? loadBilling(),
          fetchOrganizationUsage().catch(() => null),
        ]);
        if (cancelled) return;
        const low =
          Boolean(usage?.is_low_balance) ||
          Boolean(status && "is_low_balance" in status && status.is_low_balance) ||
          (typeof status?.balance === "number" && status.balance < (usage?.low_balance_threshold_kzt ?? 2500));
        setBalance(usage?.wallet_balance_kzt ?? status?.balance ?? null);
        setThreshold(usage?.low_balance_threshold_kzt ?? 2500);
        setVisible(low);
      } catch {
        if (!cancelled) setVisible(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [billing, loadBilling]);

  if (!visible) return null;

  return (
    <div className="relative z-20 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-amber-100">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-2.5 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <p>
            <span className="font-semibold text-amber-50">Низкий баланс кошелька.</span>{" "}
            {balance != null ? (
              <>
                Сейчас {formatBillingCurrency(balance, "KZT")} (порог{" "}
                {formatBillingCurrency(threshold, "KZT")}).{" "}
              </>
            ) : null}
            Пополните счёт, чтобы AI-агенты продолжали отвечать без перебоев.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/dashboard/billing"
            className="inline-flex items-center rounded-lg bg-amber-400 px-3 py-1.5 text-xs font-semibold text-zinc-950 transition hover:bg-amber-300"
          >
            Пополнить баланс
          </Link>
          <button
            type="button"
            aria-label="Dismiss low balance banner"
            onClick={() => {
              try {
                window.sessionStorage.setItem(DISMISS_KEY, String(Date.now()));
              } catch {
                // ignore
              }
              setVisible(false);
            }}
            className="rounded-lg p-1.5 text-amber-200/80 transition hover:bg-amber-500/20 hover:text-amber-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
