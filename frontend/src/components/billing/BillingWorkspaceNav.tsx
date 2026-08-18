"use client";

import {
  Bot,
  CreditCard,
  History,
  Wallet,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { BillingWorkspaceNavItem, BillingWorkspaceSection } from "@/types/billing";
import { BILLING_WORKSPACE_NAV } from "@/types/billing";

const NAV_ICONS: Record<BillingWorkspaceSection, typeof Wallet> = {
  balance: Wallet,
  subscriptions: CreditCard,
  agents: Bot,
  history: History,
  payments: CreditCard,
};

interface BillingWorkspaceNavProps {
  activeSection: BillingWorkspaceSection;
  onSectionChange: (section: BillingWorkspaceSection) => void;
}

export function BillingWorkspaceNav({
  activeSection,
  onSectionChange,
}: BillingWorkspaceNavProps) {
  return (
    <nav className="space-y-1">
      <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-600">
        Биллинг
      </p>
      {BILLING_WORKSPACE_NAV.map((item: BillingWorkspaceNavItem) => {
        const Icon = NAV_ICONS[item.id];
        const isActive = activeSection === item.id;

        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSectionChange(item.id)}
            className={cn(
              "relative flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition",
              isActive
                ? "bg-violet-500/10 text-violet-100 ring-1 ring-violet-500/20"
                : "text-zinc-400 hover:bg-zinc-900/70 hover:text-zinc-100",
            )}
          >
            {isActive ? (
              <span className="absolute bottom-2 left-0 top-2 w-0.5 rounded-full bg-violet-500" />
            ) : null}
            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", isActive ? "text-violet-400" : "text-zinc-500")} />
            <span>
              <span className="block text-sm font-medium">{item.label}</span>
              <span className="mt-0.5 block text-[11px] text-zinc-500">{item.description}</span>
            </span>
          </button>
        );
      })}
    </nav>
  );
}
