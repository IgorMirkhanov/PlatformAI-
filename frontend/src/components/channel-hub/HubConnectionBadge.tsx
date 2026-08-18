"use client";

import { cn } from "@/lib/utils";
import type { HubChannelStatus } from "@/types/channel-hub";

const LABELS: Record<HubChannelStatus, string> = {
  connected: "Подключён",
  disconnected: "Отключён",
  pending: "Ожидание",
};

export function HubConnectionBadge({
  status,
  className,
}: {
  status: HubChannelStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
        status === "connected" && "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30",
        status === "pending" && "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30",
        status === "disconnected" && "bg-zinc-800/80 text-zinc-400 ring-1 ring-zinc-700/60",
        className,
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "connected" && "bg-emerald-400",
          status === "pending" && "bg-amber-400 animate-pulse",
          status === "disconnected" && "bg-zinc-500",
        )}
      />
      {LABELS[status]}
    </span>
  );
}
