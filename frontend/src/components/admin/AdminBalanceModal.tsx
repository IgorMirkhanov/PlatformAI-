"use client";

import { useEffect, useState } from "react";
import { Loader2, Wallet, X } from "lucide-react";

import { adjustAdminOrganizationBalance } from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import { useToast } from "@/hooks/useToast";
import type { AdminOrganizationItem } from "@/types/admin";
import type { BillingCurrency } from "@/types/billing";

interface AdminBalanceModalProps {
  open: boolean;
  organization: AdminOrganizationItem | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function AdminBalanceModal({
  open,
  organization,
  onClose,
  onSuccess,
}: AdminBalanceModalProps) {
  const { showToast } = useToast();
  const [amountDelta, setAmountDelta] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setAmountDelta("");
    setReason("");
    setLoading(false);
  }, [open, organization?.id]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loading) onClose();
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKey);
    };
  }, [loading, onClose, open]);

  if (!open || !organization) return null;

  const currency = (organization.currency || "KZT") as BillingCurrency;

  const handleSubmit = async () => {
    const delta = Number(amountDelta);
    if (!Number.isFinite(delta) || delta === 0) {
      showToast("Укажите ненулевое число (можно отрицательное).", "error");
      return;
    }
    if (!reason.trim()) {
      showToast("Укажите причину для audit log.", "error");
      return;
    }

    setLoading(true);
    try {
      const result = await adjustAdminOrganizationBalance(organization.id, {
        amount_delta: delta,
        reason: reason.trim(),
      });
      showToast(
        `Баланс ${organization.name}: ${formatBillingCurrency(result.previous_balance, currency)} → ${formatBillingCurrency(result.new_balance, currency)}`,
        "success",
      );
      onSuccess();
      onClose();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось изменить баланс."), "error");
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
                Admin wallet
              </p>
            </div>
            <h3 className="text-lg font-semibold text-zinc-50">Изменить баланс</h3>
            <p className="mt-1 text-xs text-zinc-500">
              {organization.name} · текущий{" "}
              {formatBillingCurrency(organization.wallet_balance, currency)}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <label className="mb-3 block">
          <span className="mb-1.5 block text-xs font-medium text-zinc-400">
            amount_delta (KZT)
          </span>
          <input
            type="number"
            step="0.01"
            value={amountDelta}
            onChange={(e) => setAmountDelta(e.target.value)}
            placeholder="например 5000 или -1000"
            className="h-10 w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-3 text-sm text-zinc-100 outline-none focus:border-amber-500/40 focus:ring-2 focus:ring-amber-500/20"
          />
        </label>

        <label className="mb-5 block">
          <span className="mb-1.5 block text-xs font-medium text-zinc-400">Причина (audit)</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="Компенсация / корректировка / тест…"
            className="w-full resize-none rounded-xl border border-zinc-800 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-amber-500/40 focus:ring-2 focus:ring-amber-500/20"
          />
        </label>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-xl border border-zinc-800 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-900"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-amber-500/90 px-4 py-2 text-sm font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Применить
          </button>
        </div>
      </div>
    </div>
  );
}
