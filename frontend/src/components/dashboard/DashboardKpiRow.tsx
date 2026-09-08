"use client";

import { Braces, MessageSquare, Wallet } from "lucide-react";

interface DashboardKpiRowProps {
  uniqueDialogs: number;
  functionCalls: number;
  tokenSpendLabel: string;
  periodLabel?: string;
}

export function DashboardKpiRow({
  uniqueDialogs,
  functionCalls,
  tokenSpendLabel,
  periodLabel = "За месяц",
}: DashboardKpiRowProps) {
  const items = [
    {
      label: "Уникальных диалогов",
      value: String(uniqueDialogs),
      icon: MessageSquare,
    },
    {
      label: "Вызов функций",
      value: String(functionCalls),
      icon: Braces,
    },
    {
      label: "Расходы за токены",
      value: tokenSpendLabel,
      icon: Wallet,
    },
  ] as const;

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div
            key={item.label}
            className="flex items-center gap-4 rounded-2xl border border-[var(--canvas-border)] bg-[var(--card)] px-5 py-4 shadow-soft"
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
              <Icon className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-[var(--canvas-fg)]">{item.value}</p>
              <p className="text-xs text-[var(--canvas-muted)]">{item.label}</p>
              <p className="text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">{periodLabel}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
