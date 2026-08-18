import { cn } from "@/lib/utils";

interface ChannelStatusBadgeProps {
  connected: boolean;
  active: boolean;
}

export function ChannelStatusBadge({ connected, active }: ChannelStatusBadgeProps) {
  if (connected && active) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
          "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30",
          "shadow-[0_0_16px_rgba(16,185,129,0.25)]",
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.9)]" />
        Подключено
      </span>
    );
  }

  if (connected) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300 ring-1 ring-amber-500/25">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
        Подключено
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-800/80 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-500 ring-1 ring-zinc-700/60">
      <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" />
      Отключено
    </span>
  );
}
