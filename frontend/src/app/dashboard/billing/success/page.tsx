"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2 } from "lucide-react";

import { fetchOrganizationWallet } from "@/lib/api";
import { useBotStore } from "@/store/useBotStore";

export default function BillingSuccessPage() {
  const loadBilling = useBotStore((state) => state.loadBilling);
  const [walletBalance, setWalletBalance] = useState<number | null>(null);
  const [polling, setPolling] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    const poll = async () => {
      attempts += 1;
      try {
        const wallet = await fetchOrganizationWallet();
        if (!cancelled) {
          setWalletBalance(wallet.balance);
        }
        await loadBilling();
      } catch {
        // keep polling briefly while webhook settles
      }
      if (attempts < 8 && !cancelled) {
        window.setTimeout(() => void poll(), 1500);
      } else if (!cancelled) {
        setPolling(false);
      }
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [loadBilling]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-4 text-center">
      <div className="animate-in fade-in zoom-in-95 rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-8">
        <CheckCircle2 className="mx-auto h-14 w-14 text-emerald-400" />
        <h1 className="mt-4 text-2xl font-semibold text-zinc-50">Оплата прошла успешно</h1>
        <p className="mt-2 text-sm text-zinc-400">
          Баланс организации обновится в течение нескольких секунд после подтверждения платёжной
          системы.
        </p>
        <div className="mt-6 rounded-2xl border border-zinc-800 bg-black/40 px-4 py-3">
          {walletBalance === null || polling ? (
            <div className="flex items-center justify-center gap-2 text-sm text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              Загружаем баланс…
            </div>
          ) : (
            <p className="text-sm text-zinc-300">
              Текущий баланс кошелька:{" "}
              <span className="text-lg font-bold text-emerald-300">
                {walletBalance.toLocaleString("ru-RU")} credits
              </span>
            </p>
          )}
        </div>
        <Link
          href="/dashboard/billing"
          className="mt-6 inline-flex rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-500"
        >
          Вернуться в биллинг
        </Link>
      </div>
    </div>
  );
}
