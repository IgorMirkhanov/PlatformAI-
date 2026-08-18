import { Settings2 } from "lucide-react";

import { ChannelBrandIcon } from "@/components/bots/channels/ChannelBrandIcon";
import { cn } from "@/lib/utils";
import { buildWidgetEmbedScript } from "@/types/channels";
import type { ChannelDefinition, ChannelStatus } from "@/types/channels";

interface ChannelIntegrationCardProps {
  botId: string;
  definition: ChannelDefinition;
  status: ChannelStatus;
  onConfigure: () => void;
}

export function ChannelIntegrationCard({
  botId,
  definition,
  status,
  onConfigure,
}: ChannelIntegrationCardProps) {
  const isConnected = status.connected && status.active;
  const telegramHandle = status.telegram_username ? `@${status.telegram_username}` : "@YourBot";
  const widgetSnippet = status.embed_script ?? buildWidgetEmbedScript(botId);

  return (
    <article
      className={cn(
        "group relative flex min-h-[248px] flex-col overflow-hidden rounded-2xl border p-5 transition duration-300",
        "border-zinc-800/80 bg-[#0b0b0d]/90 hover:border-zinc-700/80 hover:bg-[#101014]/95",
        isConnected && definition.accentRing,
        isConnected && "shadow-[0_0_40px_rgba(16,185,129,0.06)]",
      )}
      style={
        isConnected
          ? { boxShadow: `0 0 36px ${definition.brandColor}22, inset 0 1px 0 rgba(255,255,255,0.04)` }
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
            "flex h-12 w-12 items-center justify-center rounded-xl bg-black/35 ring-1",
            definition.accentRing,
          )}
          style={{ boxShadow: isConnected ? `0 0 24px ${definition.brandColor}55` : undefined }}
        >
          <ChannelBrandIcon channelId={definition.id} className="h-7 w-7" />
        </div>

        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide",
            isConnected
              ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30"
              : "bg-zinc-800/80 text-zinc-500 ring-1 ring-zinc-700/60",
          )}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              isConnected
                ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.95)]"
                : "bg-zinc-500",
            )}
          />
          {isConnected ? "Подключено" : "Отключено"}
        </span>
      </div>

      <div className="relative mt-5 min-w-0 flex-1">
        <h3 className="truncate text-base font-semibold text-zinc-50">{definition.title}</h3>
        <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-zinc-500">
          {definition.subtitle}
        </p>
        <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-zinc-400">
          {definition.description}
        </p>

        {definition.id === "telegram" ? (
          <p className="mt-3 truncate font-mono text-xs text-cyan-300/90">{telegramHandle}</p>
        ) : null}

        {definition.id === "whatsapp" && status.metadata?.whatsapp_phone_number_id ? (
          <p className="mt-3 truncate font-mono text-xs text-emerald-300/90">
            Phone ID: {status.metadata.whatsapp_phone_number_id}
          </p>
        ) : null}

        {definition.id === "web_widget" ? (
          <pre className="mt-3 max-h-16 overflow-hidden rounded-lg border border-zinc-800/80 bg-black/50 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-violet-200/80">
            {widgetSnippet}
          </pre>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onConfigure}
        className={cn(
          "relative mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition",
          isConnected
            ? "border border-zinc-700 bg-zinc-800 hover:bg-zinc-700"
            : "bg-violet-600 hover:bg-violet-500",
          !isConnected && definition.buttonGlow,
        )}
        style={
          !isConnected
            ? { backgroundColor: `${definition.brandColor}cc`, boxShadow: `0 0 24px ${definition.brandColor}44` }
            : undefined
        }
      >
        <Settings2 className="h-4 w-4" />
        Настроить канал
      </button>
    </article>
  );
}
