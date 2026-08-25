import { Settings2, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import type { CRMPlatformStatus } from "@/types/crm";

interface CrmIntegrationCardProps {
  definition: CRMIntegrationDefinition;
  status: CRMPlatformStatus | undefined;
  onConfigure: () => void;
  onRequestAccess?: () => void;
  logoOverride?: string;
}

function statusBadgeLabel(
  connected: boolean,
  availability: CRMIntegrationDefinition["availability"],
): string {
  if (connected) return "Подключен";
  if (availability === "on_request") return "По заявке";
  return "Не подключен";
}

export function CrmIntegrationCard({
  definition,
  status,
  onConfigure,
  onRequestAccess,
  logoOverride,
}: CrmIntegrationCardProps) {
  const connected = Boolean(status?.connected);
  const onRequest = definition.availability === "on_request" && !connected;
  const logo =
    logoOverride ||
    (definition.id === "amocrm"
      ? "amo"
      : definition.id === "bitrix24"
        ? "B24"
        : definition.title.slice(0, 2));

  const badgeLabel = statusBadgeLabel(connected, definition.availability);
  const badgeConnected = connected;
  const badgePending = !connected && definition.availability === "on_request";

  const actionLabel = connected ? "Настройки" : onRequest ? "Оставить заявку" : "Подключить";

  return (
    <article
      className={cn(
        "group relative flex min-h-[220px] flex-col overflow-hidden rounded-2xl border p-5 transition duration-300",
        "border-zinc-800/80 bg-[#0b0b0d]/90 hover:border-zinc-700/80 hover:bg-[#101014]/95",
        connected && "shadow-[0_0_40px_rgba(16,185,129,0.06)]",
      )}
      style={
        connected
          ? { boxShadow: `0 0 36px ${definition.brandColor}22`, borderColor: `${definition.brandColor}33` }
          : undefined
      }
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b opacity-90",
          definition.brandGradient,
        )}
      />

      <div className="relative flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-black/35 text-sm font-bold ring-1",
              definition.accentRing,
            )}
            style={{ color: definition.brandColor }}
          >
            {logo}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-base font-semibold text-zinc-50">{definition.title}</h3>
            <span
              className={cn(
                "mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                badgeConnected
                  ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30"
                  : badgePending
                    ? "bg-amber-500/10 text-amber-200 ring-1 ring-amber-500/30"
                    : "bg-zinc-800/80 text-zinc-500 ring-1 ring-zinc-700/60",
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  badgeConnected
                    ? "bg-emerald-400"
                    : badgePending
                      ? "bg-amber-400"
                      : "bg-zinc-500",
                )}
              />
              {badgeLabel}
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={onRequest ? onRequestAccess ?? onConfigure : onConfigure}
          className={cn(
            "shrink-0 inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition",
            connected
              ? "border border-zinc-700 bg-zinc-800 text-zinc-200 hover:bg-zinc-700"
              : onRequest
                ? "border border-amber-500/40 bg-amber-500/10 text-amber-100 hover:bg-amber-500/20"
                : "bg-violet-600 text-white shadow-glow-purple hover:bg-violet-500",
          )}
          style={
            !connected && !onRequest
              ? { backgroundColor: `${definition.brandColor}cc`, boxShadow: `0 0 20px ${definition.brandColor}44` }
              : undefined
          }
        >
          {connected ? <Settings2 className="h-3.5 w-3.5" /> : onRequest ? <Sparkles className="h-3.5 w-3.5" /> : null}
          {actionLabel}
        </button>
      </div>

      <p className="relative mt-4 line-clamp-3 flex-1 text-sm leading-relaxed text-zinc-400">
        {definition.description}
      </p>
      {status?.detail ? (
        <p className="relative mt-2 truncate font-mono text-[11px] text-zinc-500">{status.detail}</p>
      ) : null}
    </article>
  );
}
