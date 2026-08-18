"use client";

import { useEffect, useState } from "react";
import { Crown, Loader2, X } from "lucide-react";

import { createWalletCheckout, fetchSubscriptionCatalog } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

interface SubscriptionModalProps {
  open: boolean;
  onClose: () => void;
}

type PlanPackage = {
  id: string;
  label: string;
  amount_usd: number;
  tokens_allocated: number;
  plan_id: string;
};

const FALLBACK_PLANS: PlanPackage[] = [
  {
    id: "sub_pro",
    label: "PRO (monthly)",
    amount_usd: 49,
    tokens_allocated: 500_000,
    plan_id: "pro",
  },
  {
    id: "sub_enterprise",
    label: "ENTERPRISE (monthly)",
    amount_usd: 199,
    tokens_allocated: 2_500_000,
    plan_id: "enterprise",
  },
];

export function SubscriptionModal({ open, onClose }: SubscriptionModalProps) {
  const { showToast } = useToast();
  const [plans, setPlans] = useState<PlanPackage[]>(FALLBACK_PLANS);
  const [selectedId, setSelectedId] = useState(FALLBACK_PLANS[0].id);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    void fetchSubscriptionCatalog()
      .then((res) => {
        if (res.plans?.length) {
          setPlans(res.plans);
          setSelectedId(res.plans[0].id);
        }
      })
      .catch(() => setPlans(FALLBACK_PLANS));
  }, [open]);

  if (!open) return null;

  const selected = plans.find((plan) => plan.id === selectedId) ?? plans[0];

  const handlePay = async () => {
    setLoading(true);
    try {
      const origin = window.location.origin;
      const result = await createWalletCheckout({
        item_type: "subscription",
        plan_or_package_id: selected.id,
        provider: "stripe",
        success_url: `${origin}/dashboard/billing/success`,
        cancel_url: `${origin}/dashboard/billing?checkout=cancel`,
      });
      const url = result.checkout_url || result.url;
      if (!url) throw new Error("Checkout URL missing.");
      window.location.assign(url);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось открыть оплату подписки."), "error");
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <button type="button" className="absolute inset-0" onClick={onClose} aria-label="Закрыть" />
      <div className="moonai-modal relative w-full max-w-lg">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-violet-300">
              <Crown className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wider">Тарифы</span>
            </div>
            <h3 className="text-lg font-semibold text-zinc-50">Подписка MP.AI</h3>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {plans.map((plan) => (
            <button
              key={plan.id}
              type="button"
              onClick={() => setSelectedId(plan.id)}
              className={cn(
                "rounded-xl border p-4 text-left transition",
                selectedId === plan.id
                  ? "border-violet-500/50 bg-violet-500/10"
                  : "border-zinc-800 hover:border-zinc-700",
              )}
            >
              <p className="font-semibold text-zinc-100">{plan.label}</p>
              <p className="mt-1 text-2xl font-bold text-violet-200">${plan.amount_usd}</p>
              <p className="mt-2 text-xs text-zinc-500">
                +{plan.tokens_allocated.toLocaleString("ru-RU")} credits / month
              </p>
            </button>
          ))}
        </div>

        <button
          type="button"
          disabled={loading}
          onClick={() => void handlePay()}
          className="mt-5 w-full rounded-xl bg-violet-600 py-3 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
        >
          {loading ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : "Оплатить подписку"}
        </button>
      </div>
    </div>
  );
}
