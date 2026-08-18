import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  subtext?: string;
  trend?: string;
  trendUp?: boolean;
  icon: LucideIcon;
  accent?: "indigo" | "emerald" | "amber" | "sky";
}

const ACCENT_MAP = {
  indigo: "from-indigo-500/20 to-indigo-500/5 text-indigo-300 ring-indigo-500/20",
  emerald: "from-emerald-500/20 to-emerald-500/5 text-emerald-300 ring-emerald-500/20",
  amber: "from-amber-500/20 to-amber-500/5 text-amber-300 ring-amber-500/20",
  sky: "from-sky-500/20 to-sky-500/5 text-sky-300 ring-sky-500/20",
};

export function MetricCard({
  label,
  value,
  subtext,
  trend,
  trendUp = true,
  icon: Icon,
  accent = "indigo",
}: MetricCardProps) {
  return (
    <div className="glass-panel group relative overflow-hidden rounded-2xl p-5 transition hover:border-accent/30">
      <div
        className={cn(
          "absolute -right-6 -top-6 h-24 w-24 rounded-full bg-gradient-to-br blur-2xl",
          ACCENT_MAP[accent],
        )}
      />
      <div className="relative flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{label}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">{value}</p>
          {subtext && <p className="mt-1 text-xs text-zinc-500">{subtext}</p>}
        </div>
        <div
          className={cn(
            "flex h-11 w-11 items-center justify-center rounded-xl ring-1",
            ACCENT_MAP[accent],
          )}
        >
          <Icon className="h-5 w-5" />
        </div>
      </div>
      {trend && (
        <div className="relative mt-4 flex items-center gap-2">
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              trendUp
                ? "bg-emerald-500/15 text-emerald-400"
                : "bg-red-500/15 text-red-400",
            )}
          >
            {trendUp ? "↑" : "↓"} {trend}
          </span>
          <span className="text-[10px] text-zinc-600">vs last period</span>
        </div>
      )}
    </div>
  );
}
