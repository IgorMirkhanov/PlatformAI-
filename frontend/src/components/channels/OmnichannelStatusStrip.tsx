"use client";

import { cn } from "@/lib/utils";
import { OMNICHANNEL_DEFINITIONS } from "@/types/channels";
import type { ChannelIntegrationType, ChannelStatus } from "@/types/channels";
import { mergeChannelStatuses } from "@/types/channels";

const CHANNEL_SHORT_LABELS: Record<ChannelIntegrationType, string> = {
  telegram: "TG",
  whatsapp: "WA",
  instagram: "IG",
  vkontakte: "VK",
  web_widget: "WEB",
};

interface OmnichannelStatusStripProps {
  statuses?: Record<ChannelIntegrationType, ChannelStatus>;
  connectedChannels?: string[];
  className?: string;
  size?: "sm" | "md";
}

export function OmnichannelStatusStrip({
  statuses,
  connectedChannels,
  className,
  size = "md",
}: OmnichannelStatusStripProps) {
  const connectedSet = new Set(
    connectedChannels ??
      OMNICHANNEL_DEFINITIONS.filter((definition) => {
        const status = statuses?.[definition.id] ?? mergeChannelStatuses([])[definition.id];
        return status.connected && status.active;
      }).map((definition) => definition.id),
  );

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {OMNICHANNEL_DEFINITIONS.map((channel) => {
        const active = connectedSet.has(channel.id);
        const status = statuses?.[channel.id];

        return (
          <span
            key={channel.id}
            title={
              active
                ? `${channel.title} · Подключено`
                : `${channel.title} · Отключено`
            }
            className={cn(
              "inline-flex items-center justify-center rounded-lg border font-bold tracking-wide transition",
              size === "sm" ? "h-7 min-w-[1.75rem] px-1.5 text-[9px]" : "h-8 min-w-[2rem] px-2 text-[10px]",
              active
                ? "border-transparent text-white"
                : "border-zinc-800 bg-zinc-950/80 text-zinc-600",
            )}
            style={
              active
                ? {
                    backgroundColor: `${channel.brandColor}22`,
                    boxShadow: `0 0 16px ${channel.brandColor}66`,
                    color: channel.brandColor,
                  }
                : undefined
            }
          >
            {CHANNEL_SHORT_LABELS[channel.id]}
            {active && status?.telegram_username && channel.id === "telegram" ? (
              <span className="sr-only">@{status.telegram_username}</span>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}
