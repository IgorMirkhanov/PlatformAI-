"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { createPortal } from "react-dom";

import { PricingTierGrid } from "@/components/billing/PricingTierGrid";
import type { SubscriptionPlanName } from "@/types/billing";

interface BillingModalProps {
  open: boolean;
  onClose: () => void;
  currentPlan: SubscriptionPlanName;
  onSelectPlan: (plan: SubscriptionPlanName) => Promise<void>;
  loading?: boolean;
}

export function BillingModal({
  open,
  onClose,
  currentPlan,
  onSelectPlan,
  loading = false,
}: BillingModalProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!open || !mounted) {
    return null;
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <button
        type="button"
        className="absolute inset-0"
        onClick={onClose}
        aria-label="Close billing modal"
      />
      <div className="relative m-auto max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-surface-border bg-surface-raised p-6 shadow-node">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-zinc-100">Upgrade your workspace</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Choose a plan that matches your agent volume and automation needs.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-400 hover:bg-surface-overlay"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <PricingTierGrid
          currentPlan={currentPlan}
          onSelectPlan={onSelectPlan}
          loading={loading}
        />
      </div>
    </div>,
    document.body,
  );
}
