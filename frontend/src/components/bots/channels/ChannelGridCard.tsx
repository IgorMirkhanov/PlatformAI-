import { Plug, Settings2 } from "lucide-react";

import { ChannelBrandIcon } from "@/components/bots/channels/ChannelBrandIcon";
import { cn } from "@/lib/utils";
import type { ChannelDefinition, ChannelStatus } from "@/types/channels";

interface ChannelGridCardProps {
  definition: ChannelDefinition;
  status: ChannelStatus;
  onConfigure: () => void;
}

export function ChannelGridCard({ definition, status, onConfigure }: ChannelGridCardProps) {
  const isLive = status.connected && status.active;

  return (
    <article
      className={cn(
        "group relative flex min-h-[220px] flex-col overflow-hidden rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/90 p-5 transition duration-300",
        "hover:border-zinc-700/80 hover:bg-[#101014]/95",
        isLive && "border-emerald-500/20 shadow-[0_0_32px_rgba(16,185,129,0.08)]",
      )}
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b opacity-80",
          definition.brandGradient,
        )}
      />

      <div className="relative flex items-start justify-between gap-3">
        <div
          className={cn(
            "flex h-11 w-11 items-center justify-center rounded-xl bg-black/30 ring-1",
            definition.accentRing,
          )}
        >
          <ChannelBrandIcon channelId={definition.id} className="h-6 w-6" />
        </div>

        <button
          type="button"
          onClick={onConfigure}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold text-white transition",
            isLive
              ? "bg-zinc-800 hover:bg-zinc-700"
              : "bg-violet-600 hover:bg-violet-500",
            !isLive && definition.buttonGlow,
          )}
        >
          {isLive ? (
            <>
              <Settings2 className="h-3.5 w-3.5" />
              Настроить
            </>
          ) : (
            <>
              <Plug className="h-3.5 w-3.5" />
              Подключить
            </>
          )}
        </button>
      </div>

      <div className="relative mt-5 flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold text-zinc-50">{definition.title}</h3>
        <span
          className={cn(
            "text-xs font-medium",
            isLive ? "text-emerald-400" : "text-zinc-500",
          )}
        >
          {isLive ? "Подключено" : "Не подключено"}
        </span>
      </div>

      <p className="relative mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-zinc-500">
        {definition.subtitle}
      </p>

      <p className="relative mt-3 flex-1 text-sm leading-relaxed text-zinc-400">
        {definition.description}
      </p>

      {status.telegram_username ? (
        <p className="relative mt-3 text-xs text-zinc-500">
          @{status.telegram_username}
        </p>
      ) : null}
    </article>
  );
}
