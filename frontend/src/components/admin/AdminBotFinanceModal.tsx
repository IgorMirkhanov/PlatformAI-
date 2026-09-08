"use client";

import { useEffect, useState } from "react";
import { Loader2, Wallet, X } from "lucide-react";

import { adjustAdminBotBalance, setAdminBotSubscription } from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";
import { useToast } from "@/hooks/useToast";
import type { AdminBotItem } from "@/types/admin";

interface AdminBotFinanceModalProps {
  open: boolean;
  bot: AdminBotItem | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function AdminBotFinanceModal({
  open,
  bot,
  onClose,
  onSuccess,
}: AdminBotFinanceModalProps) {
  const { showToast } = useToast();
  const [amountDelta, setAmountDelta] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setAmountDelta("");
    setReason("");
    setLoading(false);
  }, [open, bot?.id]);

  if (!open || !bot) return null;

  const handleBalance = async () => {
    const delta = Number(amountDelta);
    if (!Number.isFinite(delta) || delta === 0) {
      showToast("Укажите ненулевое число кредитов.", "error");
      return;
    }
    if (!reason.trim()) {
      showToast("Укажите причину для audit log.", "error");
      return;
    }
    setLoading(true);
    try {
      const result = await adjustAdminBotBalance(bot.id, {
        amount_delta: Math.trunc(delta),
        reason: reason.trim(),
      });
      showToast(
        `${bot.name}: баланс ${result.previous_balance} → ${result.new_balance}`,
        "success",
      );
      onSuccess();
      onClose();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось изменить баланс бота."), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleSubscription = async (active: boolean) => {
    if (!reason.trim()) {
      showToast("Укажите причину для audit log.", "error");
      return;
    }
    setLoading(true);
    try {
      const result = await setAdminBotSubscription(bot.id, {
        active,
        reason: reason.trim(),
      });
      showToast(result.message, "success");
      onSuccess();
      onClose();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось изменить подписку бота."), "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <button type="button" className="absolute inset-0" onClick={onClose} aria-label="Закрыть" />
      <div className="relative w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950 p-5 shadow-2xl">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Wallet className="h-4 w-4 text-amber-300" />
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
                Подписка и баланс бота
              </p>
            </div>
            <h3 className="text-lg font-semibold text-zinc-50">{bot.name}</h3>
            <p className="mt-1 text-xs text-zinc-500">
              {bot.organization_name || "—"} · баланс {bot.wallet_balance ?? 0} ·{" "}
              {bot.subscription_active ? "подписка включена" : "подписки нет"}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900">
            <X className="h-4 w-4" />
          </button>
        </div>

        <label className="mb-3 block">
          <span className="mb-1.5 block text-xs font-medium text-zinc-400">Кредиты (+ пополнить / − списать)</span>
          <input
            type="number"
            step="1"
            value={amountDelta}
            onChange={(event) => setAmountDelta(event.target.value)}
            placeholder="например 5000 или -1000"
            className="h-10 w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-3 text-sm text-zinc-100 outline-none focus:border-amber-500/40"
          />
        </label>

        <label className="mb-5 block">
          <span className="mb-1.5 block text-xs font-medium text-zinc-400">Причина (audit)</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            className="w-full resize-none rounded-xl border border-zinc-800 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 outline-none"
          />
        </label>

        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={() => void handleSubscription(!(bot.subscription_active ?? false))}
            disabled={loading}
            className="rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900"
          >
            {bot.subscription_active ? "Выключить подписку" : "Включить подписку"}
          </button>
          <button
            type="button"
            onClick={() => void handleBalance()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-amber-500/90 px-4 py-2 text-sm font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Изменить баланс
          </button>
        </div>
      </div>
    </div>
  );
}
