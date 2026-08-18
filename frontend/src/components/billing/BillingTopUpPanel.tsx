"use client";

import { useState } from "react";
import { Loader2, Wallet } from "lucide-react";

import { formatBillingCurrency } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { TOP_UP_PRESETS_KZT } from "@/types/billing";

interface BillingTopUpPanelProps {
  currency: "KZT" | "USD";
  onTopUp: (amount: number) => Promise<void>;
}

export function BillingTopUpPanel({ currency, onTopUp }: BillingTopUpPanelProps) {
  const [amount, setAmount] = useState<number>(TOP_UP_PRESETS_KZT[1]);
  const [customAmount, setCustomAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (): Promise<void> => {
    const parsedCustom = customAmount.trim() ? Math.trunc(Number(customAmount)) : NaN;
    const finalAmount = customAmount.trim() ? parsedCustom : Math.trunc(amount);

    if (!Number.isFinite(finalAmount) || finalAmount <= 0) {
      setError("Введите сумму больше нуля.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await onTopUp(finalAmount);
      setCustomAmount(String(finalAmount));
      setAmount(finalAmount);
    } catch {
      setError("Пополнение не удалось. Попробуйте снова.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="relative overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-950/60 p-6 backdrop-blur-xl">
      {loading ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-black/50 backdrop-blur-[2px]">
          <div className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950/90 px-4 py-3 text-sm text-zinc-200">
            <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
            Обработка платежа…
          </div>
        </div>
      ) : null}

      <div className="mb-5 flex items-center gap-2">
        <Wallet className="h-4 w-4 text-violet-400" />
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Пополнение баланса</h3>
          <p className="text-xs text-zinc-500">Быстрые пресеты и произвольная сумма</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {TOP_UP_PRESETS_KZT.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => {
              const integerAmount = Math.trunc(preset);
              setAmount(integerAmount);
              setCustomAmount(String(integerAmount));
            }}
            className={cn(
              "rounded-xl border px-3.5 py-2.5 text-sm font-semibold transition",
              amount === preset
                ? "border-violet-500/50 bg-violet-500/15 text-violet-200 shadow-glow-purple"
                : "border-zinc-800 text-zinc-300 hover:border-zinc-700 hover:bg-zinc-900/70",
            )}
          >
            {formatBillingCurrency(preset, currency)}
          </button>
        ))}
      </div>

      <div className="mt-5">
        <label htmlFor="billing-custom-amount" className="text-xs text-zinc-500">
          Сумма пополнения
        </label>
        <input
          id="billing-custom-amount"
          type="number"
          min="1"
          step="1"
          value={customAmount || String(amount)}
          onChange={(event) => {
            const next = event.target.value;
            setCustomAmount(next);
            const parsed = Math.trunc(Number(next));
            if (Number.isFinite(parsed) && parsed > 0) {
              setAmount(parsed);
            }
          }}
          placeholder="Введите сумму в ₸"
          className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
        />
      </div>

      {error ? <p className="mt-3 text-xs text-rose-400">{error}</p> : null}

      <button
        type="button"
        onClick={() => void handleSubmit()}
        disabled={loading}
        className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-3 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Пополнить баланс
      </button>
    </section>
  );
}
