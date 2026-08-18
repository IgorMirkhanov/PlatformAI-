"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, Wallet, X, Zap } from "lucide-react";

import { createWalletCheckout, fetchTopUpCatalog } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

interface TopUpModalProps {
  open: boolean;
  onClose: () => void;
}

type TopUpPackage = {
  id: string;
  label: string;
  amount_usd: number;
  tokens_allocated: number;
};

const FALLBACK_PACKAGES: TopUpPackage[] = [
  { id: "topup_100k", label: "100k tokens", amount_usd: 10, tokens_allocated: 100_000 },
  { id: "topup_1m", label: "1M tokens", amount_usd: 80, tokens_allocated: 1_000_000 },
];

export function TopUpModal({ open, onClose }: TopUpModalProps) {
  const { showToast } = useToast();
  const [packages, setPackages] = useState<TopUpPackage[]>(FALLBACK_PACKAGES);
  const [selectedId, setSelectedId] = useState(FALLBACK_PACKAGES[0].id);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    void fetchTopUpCatalog()
      .then((res) => {
        if (res.packages?.length) {
          setPackages(res.packages);
          setSelectedId(res.packages[0].id);
        }
      })
      .catch(() => {
        setPackages(FALLBACK_PACKAGES);
      });
  }, [open]);

  if (!open || !mounted) return null;

  const selected = packages.find((pkg) => pkg.id === selectedId) ?? packages[0];

  const handlePay = async () => {
    setLoading(true);
    try {
      const origin = window.location.origin;
      const result = await createWalletCheckout({
        item_type: "topup",
        plan_or_package_id: selected.id,
        provider: "stripe",
        success_url: `${origin}/dashboard/billing/success`,
        cancel_url: `${origin}/dashboard/billing?checkout=cancel`,
      });
      const url = result.checkout_url || result.url;
      if (!url) {
        throw new Error("Checkout URL missing.");
      }
      window.location.assign(url);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось открыть оплату."), "error");
      setLoading(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <button type="button" className="absolute inset-0" onClick={onClose} aria-label="Закрыть" />
      <div className="moonai-modal relative m-auto w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Wallet className="h-4 w-4 text-violet-400" />
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-300/80">
                Пакеты токенов
              </p>
            </div>
            <h3 className="text-lg font-semibold text-zinc-50">Пополнение баланса</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-2">
          {packages.map((pkg) => (
            <button
              key={pkg.id}
              type="button"
              onClick={() => setSelectedId(pkg.id)}
              className={cn(
                "flex items-center justify-between rounded-xl border px-4 py-3 text-left transition",
                selectedId === pkg.id
                  ? "border-violet-500/50 bg-violet-500/10"
                  : "border-zinc-800 hover:border-zinc-700",
              )}
            >
              <div>
                <p className="font-medium text-zinc-100">{pkg.label}</p>
                <p className="text-xs text-zinc-500">
                  {pkg.tokens_allocated.toLocaleString("ru-RU")} credits
                </p>
              </div>
              <p className="text-sm font-semibold text-violet-200">${pkg.amount_usd}</p>
            </button>
          ))}
        </div>

        <button
          type="button"
          disabled={loading}
          onClick={() => void handlePay()}
          className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
          Оплатить {selected ? `$${selected.amount_usd}` : ""}
        </button>
      </div>
    </div>,
    document.body,
  );
}
