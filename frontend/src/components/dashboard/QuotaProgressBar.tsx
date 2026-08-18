"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { cn } from "@/lib/utils";

export interface QuotaMetric {
  label: string;
  used: number;
  limit: number;
}

interface QuotaProgressBarProps {
  metrics: QuotaMetric[];
  className?: string;
  compact?: boolean;
}

function ratioTone(ratio: number): string {
  if (ratio >= 1) return "bg-red-500";
  if (ratio >= 0.8) return "bg-amber-400";
  return "bg-violet-500";
}

function ratioLabelTone(ratio: number): string {
  if (ratio >= 1) return "text-red-300";
  if (ratio >= 0.8) return "text-amber-300";
  return "text-zinc-400";
}

export function QuotaProgressBar({ metrics, className, compact = false }: QuotaProgressBarProps) {
  const atCapacity = metrics.some((m) => m.limit > 0 && m.used / m.limit >= 1);
  const nearCapacity = metrics.some((m) => m.limit > 0 && m.used / m.limit >= 0.8);

  return (
    <div
      className={cn(
        "rounded-2xl border border-zinc-800/80 bg-zinc-950/60",
        compact ? "p-3" : "p-4",
        className,
      )}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
          Workspace quotas
        </p>
        {(atCapacity || nearCapacity) && (
          <Link
            href="/dashboard/billing"
            className="inline-flex items-center gap-1 rounded-lg bg-violet-500/15 px-2 py-1 text-[11px] font-semibold text-violet-200 ring-1 ring-violet-500/30 transition hover:bg-violet-500/25"
          >
            Upgrade Plan
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        )}
      </div>

      <div className={cn("space-y-3", compact && "space-y-2.5")}>
        {metrics.map((metric) => {
          const limit = Math.max(metric.limit, 0);
          const ratio = limit === 0 ? 0 : Math.min(metric.used / limit, 1);
          const pct = Math.round(ratio * 100);
          return (
            <div key={metric.label}>
              <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                <span className="font-medium text-zinc-300">{metric.label}</span>
                <span className={cn("tabular-nums", ratioLabelTone(ratio))}>
                  {metric.used} / {limit || "∞"}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-zinc-900">
                <div
                  className={cn("h-full rounded-full transition-all duration-300", ratioTone(ratio))}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
