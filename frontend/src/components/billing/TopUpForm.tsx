"use client";

import { useState } from "react";
import { Loader2, Wallet } from "lucide-react";

import { formatBillingCurrency } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { DEFAULT_BILLING_CURRENCY, TOP_UP_PRESETS_KZT } from "@/types/billing";

interface TopUpFormProps {
  onTopUp: (amount: number) => Promise<void>;
}

export function TopUpForm({ onTopUp }: TopUpFormProps) {
  const [amount, setAmount] = useState<number>(TOP_UP_PRESETS_KZT[1]);
  const [customAmount, setCustomAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (): Promise<void> => {
    const parsedCustom = customAmount.trim() ? Number(customAmount) : NaN;
    const finalAmount = customAmount.trim() ? parsedCustom : amount;

    if (!Number.isFinite(finalAmount) || finalAmount <= 0) {
      setError("Введите сумму больше нуля.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await onTopUp(finalAmount);
      setCustomAmount("");
    } catch {
      setError("Пополнение не удалось. Попробуйте снова.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="glass-card">
      <div className="mb-4 flex items-center gap-2">
        <Wallet className="h-4 w-4 text-violet-400" />
        <h3 className="text-sm font-semibold text-zinc-100">Пополнение баланса</h3>
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
              "rounded-lg border px-3 py-2 text-sm font-medium transition",
              amount === preset
                ? "border-violet-500/40 bg-violet-500/15 text-violet-300"
                : "border-zinc-800 text-zinc-300 hover:border-zinc-700 hover:bg-zinc-800/50",
            )}
          >
            {formatBillingCurrency(preset, DEFAULT_BILLING_CURRENCY)}
          </button>
        ))}
      </div>

      <div className="mt-4">
        <label htmlFor="custom-amount" className="text-xs text-zinc-500">
          Своя сумма (₸)
        </label>
        <input
          id="custom-amount"
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
          placeholder="Введите сумму"
          className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
        />
      </div>

      {error && <p className="mt-3 text-xs text-red-400">{error}</p>}

      <button
        type="button"
        onClick={() => void handleSubmit()}
        disabled={loading}
        className="mt-4 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-500 hover:shadow-glow-purple disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Пополнить
      </button>
    </div>
  );
}
