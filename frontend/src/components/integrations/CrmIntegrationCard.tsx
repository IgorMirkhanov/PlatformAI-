import { Settings2 } from "lucide-react";

import { Toggle } from "@/components/ui/Toggle";
import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import type { CRMPlatformStatus } from "@/types/crm";

interface CrmIntegrationCardProps {
  definition: CRMIntegrationDefinition;
  status: CRMPlatformStatus | undefined;
  toggling: boolean;
  onToggleSync: (enabled: boolean) => void;
  onConfigure: () => void;
  logoOverride?: string;
}

export function CrmIntegrationCard({
  definition,
  status,
  toggling,
  onToggleSync,
  onConfigure,
  logoOverride,
}: CrmIntegrationCardProps) {
  const connected = Boolean(status?.connected);
  const syncEnabled = Boolean(status?.sync_enabled);
  const isLive = connected && syncEnabled;
  const logo =
    logoOverride ||
    (definition.id === "amocrm" ? "amo" : definition.id === "bitrix24" ? "B24" : definition.title.slice(0, 2));

  return (
    <article
      className={cn(
        "group relative flex min-h-[260px] flex-col overflow-hidden rounded-2xl border p-5 transition duration-300",
        "border-zinc-800/80 bg-[#0b0b0d]/90 hover:border-zinc-700/80 hover:bg-[#101014]/95",
        isLive && "shadow-[0_0_40px_rgba(16,185,129,0.06)]",
      )}
      style={
        isLive
          ? { boxShadow: `0 0 36px ${definition.brandColor}22`, borderColor: `${definition.brandColor}33` }
          : undefined
      }
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b opacity-90",
          definition.brandGradient,
        )}
      />

      <div className="relative flex items-start justify-between gap-3">
        <div
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-xl bg-black/35 text-lg font-bold ring-1",
            definition.accentRing,
          )}
          style={{ color: definition.brandColor }}
        >
          {logo}
        </div>

        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide",
            connected
              ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30"
              : "bg-zinc-800/80 text-zinc-500 ring-1 ring-zinc-700/60",
          )}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              connected
                ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.95)]"
                : "bg-zinc-500",
            )}
          />
          {connected ? "Подключено" : "Отключено"}
        </span>
      </div>

      <div className="relative mt-5 min-w-0 flex-1">
        <h3 className="truncate text-base font-semibold text-zinc-50">{definition.title}</h3>
        <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-zinc-400">
          {definition.description}
        </p>
        {status?.detail ? (
          <p className="mt-3 truncate font-mono text-[11px] text-zinc-500">{status.detail}</p>
        ) : null}
      </div>

      <div className="relative mt-4 rounded-xl border border-zinc-800/80 bg-black/25 px-3 py-3">
        <Toggle
          checked={syncEnabled}
          disabled={!connected || toggling}
          onChange={onToggleSync}
          label="Синхронизация"
          description="Включить или отключить автоматические действия интеграции"
        />
      </div>

      <button
        type="button"
        onClick={onConfigure}
        className={cn(
          "relative mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition",
          connected
            ? "border border-zinc-700 bg-zinc-800 hover:bg-zinc-700"
            : "bg-violet-600 hover:bg-violet-500 shadow-glow-purple",
        )}
        style={
          !connected
            ? { backgroundColor: `${definition.brandColor}cc`, boxShadow: `0 0 24px ${definition.brandColor}44` }
            : undefined
        }
      >
        <Settings2 className="h-4 w-4" />
        Настроить интеграцию
      </button>
    </article>
  );
}
