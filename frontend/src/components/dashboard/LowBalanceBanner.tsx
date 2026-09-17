"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, X } from "lucide-react";

import { BalanceTopUpModal } from "@/components/billing/ManualDepositWidget";
import {
  fetchDashboardStats,
  fetchOrganizationUsage,
  fetchTokenWallet,
} from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { canAccessBilling } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY } from "@/types/billing";

const DISMISS_KEY = "mpai_low_balance_banner_dismissed_at";
const DISMISS_TTL_MS = 6 * 60 * 60 * 1000;
/** Agent credit wallet (bots.wallet_balance) — paid LLM stops near zero. */
const AGENT_WALLET_LOW_THRESHOLD = 100;
const POLL_MS = 30_000;

type AlertKind = "org" | "token" | "agent" | "blocked";

interface AlertState {
  kind: AlertKind;
  critical: boolean;
  title: string;
  detail: string;
  balanceLabel?: string;
}

function readDismissedAt(): number {
  try {
    const raw = window.sessionStorage.getItem(DISMISS_KEY);
    return raw ? Number(raw) : 0;
  } catch {
    return 0;
  }
}

function writeDismissedAt(): void {
  try {
    window.sessionStorage.setItem(DISMISS_KEY, String(Date.now()));
  } catch {
    // ignore
  }
}

export function LowBalanceBanner() {
  const currentUser = useBotStore((s) => s.currentUser);
  const loadBilling = useBotStore((s) => s.loadBilling);
  const [alert, setAlert] = useState<AlertState | null>(null);
  const [topUpOpen, setTopUpOpen] = useState(false);
  const canBill = canAccessBilling(currentUser?.role);

  const refresh = useCallback(async () => {
    if (!canBill) {
      setAlert(null);
      return;
    }

    try {
      const [status, usage, wallet, dashboard] = await Promise.all([
        loadBilling().catch(() => useBotStore.getState().billing),
        fetchOrganizationUsage().catch(() => null),
        fetchTokenWallet().catch(() => null),
        fetchDashboardStats().catch(() => null),
      ]);

      const orgThreshold =
        usage?.low_balance_threshold_kzt ??
        status?.low_balance_threshold_kzt ??
        2500;
      const orgBalance =
        usage?.wallet_balance_kzt ??
        (typeof status?.balance === "number" ? status.balance : null);
      const currency = status?.currency ?? DEFAULT_BILLING_CURRENCY;

      const tokenBlocked = wallet?.status === "blocked";
      const tokenBalance =
        typeof wallet?.balance_tokens === "number" ? wallet.balance_tokens : null;
      const tokenThreshold =
        typeof wallet?.low_balance_threshold === "number"
          ? wallet.low_balance_threshold
          : 1000;
      const tokenLow =
        tokenBalance != null && tokenBalance < tokenThreshold && !tokenBlocked;

      const lowAgents =
        dashboard?.agents?.filter((agent) => {
          if (agent.subscription_active === false) return false;
          const bal = agent.wallet_balance;
          return typeof bal === "number" && bal <= AGENT_WALLET_LOW_THRESHOLD;
        }) ?? [];

      const orgLow =
        Boolean(usage?.is_low_balance) ||
        Boolean(status?.is_low_balance) ||
        (orgBalance != null && orgBalance < orgThreshold);
      const orgCritical = orgBalance != null && orgBalance <= 0;

      let next: AlertState | null = null;

      if (tokenBlocked) {
        next = {
          kind: "blocked",
          critical: true,
          title: "Кошелёк заблокирован — ИИ остановлен",
          detail:
            tokenBalance != null
              ? `Остаток ${tokenBalance} ток. Пополните счёт, чтобы агенты снова отвечали.`
              : "Пополните счёт, чтобы агенты снова отвечали.",
          balanceLabel:
            orgBalance != null
              ? formatBillingCurrency(orgBalance, currency)
              : undefined,
        };
      } else if (orgCritical || (orgLow && orgBalance != null && orgBalance < orgThreshold * 0.2)) {
        next = {
          kind: "org",
          critical: true,
          title: "Критически низкий баланс организации",
          detail: `Сейчас ${formatBillingCurrency(orgBalance ?? 0, currency)} (порог ${formatBillingCurrency(orgThreshold, currency)}). AI-ответы могут остановиться.`,
          balanceLabel: formatBillingCurrency(orgBalance ?? 0, currency),
        };
      } else if (lowAgents.some((a) => (a.wallet_balance ?? 0) <= 0)) {
        const empty = lowAgents.filter((a) => (a.wallet_balance ?? 0) <= 0);
        const names = empty
          .slice(0, 2)
          .map((a) => a.bot_name)
          .join(", ");
        const more = empty.length > 2 ? ` и ещё ${empty.length - 2}` : "";
        next = {
          kind: "agent",
          critical: true,
          title: "Баланс агента исчерпан",
          detail: `${names}${more}: платные модели не отвечают, пока не пополните баланс агента.`,
        };
      } else if (orgLow) {
        next = {
          kind: "org",
          critical: false,
          title: "Низкий баланс кошелька",
          detail: `Сейчас ${formatBillingCurrency(orgBalance ?? 0, currency)} (порог ${formatBillingCurrency(orgThreshold, currency)}). Пополните счёт заранее.`,
          balanceLabel: formatBillingCurrency(orgBalance ?? 0, currency),
        };
      } else if (tokenLow) {
        next = {
          kind: "token",
          critical: false,
          title: "Мало токенов в кошельке",
          detail: `Остаток ${tokenBalance} ток. (порог ${tokenThreshold}).`,
        };
      } else if (lowAgents.length > 0) {
        const names = lowAgents
          .slice(0, 2)
          .map((a) => `${a.bot_name} (${a.wallet_balance ?? 0})`)
          .join(", ");
        const more = lowAgents.length > 2 ? ` и ещё ${lowAgents.length - 2}` : "";
        next = {
          kind: "agent",
          critical: false,
          title: "Низкий баланс агента",
          detail: `${names}${more}. Пополните баланс агента, чтобы не было пауз в ответах.`,
        };
      }

      if (next && !next.critical) {
        const dismissedAt = readDismissedAt();
        if (dismissedAt && Date.now() - dismissedAt < DISMISS_TTL_MS) {
          setAlert(null);
          return;
        }
      }

      setAlert(next);
    } catch {
      setAlert(null);
    }
  }, [canBill, loadBilling]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (!alert) return null;

  return (
    <>
      <div
        data-testid={
          alert.kind === "blocked" ? "wallet-blocked-banner" : "low-balance-banner"
        }
        className={cn(
          "relative z-20 border-b px-4 py-2.5",
          alert.critical
            ? "border-rose-500/40 bg-rose-500/15 text-rose-50"
            : "border-amber-500/30 bg-amber-500/10 text-amber-100",
        )}
      >
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5 text-sm">
            <AlertTriangle
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0",
                alert.critical ? "text-rose-300" : "text-amber-300",
              )}
            />
            <p className="min-w-0">
              <span
                className={cn(
                  "font-semibold",
                  alert.critical ? "text-rose-50" : "text-amber-50",
                )}
              >
                {alert.title}.
              </span>{" "}
              <span className={alert.critical ? "text-rose-100/90" : "text-amber-100/90"}>
                {alert.detail}
              </span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            {alert.kind === "agent" ? (
              <Link
                href="/dashboard/billing"
                className={cn(
                  "inline-flex items-center rounded-lg px-3 py-1.5 text-xs font-semibold transition",
                  alert.critical
                    ? "bg-rose-400 text-zinc-950 hover:bg-rose-300"
                    : "bg-amber-400 text-zinc-950 hover:bg-amber-300",
                )}
              >
                К биллингу
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => setTopUpOpen(true)}
                className={cn(
                  "inline-flex items-center rounded-lg px-3 py-1.5 text-xs font-semibold transition",
                  alert.critical
                    ? "bg-rose-400 text-zinc-950 hover:bg-rose-300"
                    : "bg-amber-400 text-zinc-950 hover:bg-amber-300",
                )}
              >
                Пополнить
              </button>
            )}
            {!alert.critical ? (
              <button
                type="button"
                aria-label="Скрыть предупреждение о балансе"
                onClick={() => {
                  writeDismissedAt();
                  setAlert(null);
                }}
                className="rounded-lg p-1.5 text-amber-200/80 transition hover:bg-amber-500/20 hover:text-amber-50"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <BalanceTopUpModal
        open={topUpOpen}
        onClose={() => {
          setTopUpOpen(false);
          void refresh();
        }}
      />
    </>
  );
}
