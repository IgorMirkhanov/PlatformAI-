import { Lock, Plug } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";

interface IntegrationGridCardProps {
  definition: CRMIntegrationDefinition;
  connected: boolean;
  onConnect: () => void;
}

export function IntegrationGridCard({ definition, connected, onConnect }: IntegrationGridCardProps) {
  return (
    <article
      className={cn(
        "group relative flex min-h-[220px] flex-col overflow-hidden rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/90 p-5 transition duration-300",
        "hover:border-zinc-700/80 hover:bg-[#101014]/95",
        connected && "border-emerald-500/20 shadow-[0_0_32px_rgba(16,185,129,0.08)]",
        !definition.available && "opacity-80",
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
          <Plug className="h-5 w-5" style={{ color: definition.brandColor }} />
        </div>

        <button
          type="button"
          onClick={onConnect}
          disabled={!definition.available}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold text-white transition",
            definition.available
              ? "bg-violet-600 hover:bg-violet-500"
              : "cursor-not-allowed bg-zinc-800 text-zinc-500",
          )}
        >
          {!definition.available ? (
            <Lock className="h-3.5 w-3.5" />
          ) : (
            <Plug className="h-3.5 w-3.5" />
          )}
          {connected ? "Настроить" : "Подключить"}
        </button>
      </div>

      <div className="relative mt-5 flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold text-zinc-50">{definition.title}</h3>
        <span
          className={cn(
            "text-xs font-medium",
            connected ? "text-emerald-400" : "text-zinc-500",
          )}
        >
          {connected ? "Подключено" : "Не подключено"}
        </span>
      </div>

      <p className="relative mt-3 flex-1 text-sm leading-relaxed text-zinc-400">
        {definition.description}
      </p>
    </article>
  );
}
