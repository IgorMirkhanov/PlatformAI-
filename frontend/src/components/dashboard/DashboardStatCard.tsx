import type { LucideIcon } from "lucide-react";

interface DashboardStatCardProps {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
}

export function DashboardStatCard({ label, value, hint, icon: Icon }: DashboardStatCardProps) {
  return (
    <div className="group rounded-2xl border border-zinc-800/70 bg-gradient-to-br from-[#101012] to-[#09090b] p-6 transition hover:border-violet-500/25 hover:shadow-glow-purple">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{label}</p>
          <p className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50">{value}</p>
          {hint && <p className="mt-2 text-xs text-zinc-600">{hint}</p>}
        </div>
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/20 transition group-hover:bg-violet-500/15">
          <Icon className="h-4 w-4 text-violet-400" />
        </div>
      </div>
    </div>
  );
}
