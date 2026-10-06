"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";

import { useToast } from "@/hooks/useToast";
import { transferOrgBalanceToBot } from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";

export interface FundBotOption {
  id: string;
  name: string;
}

interface FundBotFromOrgModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  bot?: FundBotOption | null;
  bots?: FundBotOption[];
}

export function FundBotFromOrgModal({
  open,
  onClose,
  onSuccess,
  bot = null,
  bots = [],
}: FundBotFromOrgModalProps) {
  const { showToast } = useToast();
  const billing = useBotStore((state) => state.billing);
  const loadBilling = useBotStore((state) => state.loadBilling);
  const [amount, setAmount] = useState("");
  const [botId, setBotId] = useState(bot?.id ?? "");
  const [loading, setLoading] = useState(false);
  const firstBotId = bots[0]?.id ?? "";

  useEffect(() => {
    if (!open) return;
    setAmount("");
    setBotId(bot?.id ?? firstBotId);
    setLoading(false);
    void loadBilling();
  }, [open, bot?.id, firstBotId, loadBilling]);

  const options = useMemo(() => {
    if (bot) return [bot];
    return bots;
  }, [bot, bots]);

  if (!open) return null;

  const orgBalance = billing?.balance ?? 0;
  const selected = options.find((item) => item.id === botId) ?? null;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const credits = Number(amount);
    if (!selected) {
      showToast("Выберите агента.", "error");
      return;
    }
    if (!Number.isInteger(credits) || credits <= 0) {
      showToast("Укажите целую сумму в тенге больше нуля.", "error");
      return;
    }
    if (credits > orgBalance) {
      showToast("На балансе организации не хватает средств.", "error");
      return;
    }
    setLoading(true);
    try {
      const result = await transferOrgBalanceToBot(selected.id, credits);
      showToast(
        `${result.bot_name}: на балансе агента ${result.bot_balance} кредитов.`,
        "success",
      );
      await loadBilling();
      onSuccess();
      onClose();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось перевести средства."), "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <form
        onSubmit={(event) => void handleSubmit(event)}
        className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-50">Пополнить агента</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Сумма спишется с баланса организации. 1 ₸ становится 1 кредитом на агенте.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mt-4 text-sm text-zinc-300">
          Доступно: {formatBillingCurrency(orgBalance, billing?.currency ?? "KZT")}
        </p>

        {bot ? (
          <p className="mt-3 text-sm text-zinc-200">{bot.name}</p>
        ) : (
          <label className="mt-4 block text-xs font-medium text-zinc-400">
            Агент
            <select
              value={botId}
              onChange={(event) => setBotId(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 outline-none"
            >
              {options.length === 0 ? <option value="">Нет агентов</option> : null}
              {options.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="mt-4 block text-xs font-medium text-zinc-400">
          Сумма, ₸
          <input
            inputMode="numeric"
            value={amount}
            onChange={(event) => setAmount(event.target.value.replace(/[^\d]/g, ""))}
            placeholder="1000"
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 outline-none"
          />
        </label>

        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-xl border border-zinc-800 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-900"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={loading || !selected}
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-amber-300 disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Перевести
          </button>
        </div>
      </form>
    </div>
  );
}
