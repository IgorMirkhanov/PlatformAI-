"use client";

import { ChannelBrandIcon } from "@/components/bots/channels/ChannelBrandIcon";
import { cn } from "@/lib/utils";
import { OMNICHANNEL_DEFINITIONS } from "@/types/channels";
import type { ChannelIntegrationType, ChannelStatus } from "@/types/channels";
import { mergeChannelStatuses } from "@/types/channels";

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

  const box = size === "sm" ? "h-7 w-7" : "h-8 w-8";
  const icon = size === "sm" ? "h-4 w-4" : "h-5 w-5";

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
              "inline-flex items-center justify-center rounded-full transition",
              box,
              active
                ? "ring-1 ring-white/10"
                : "bg-zinc-950/80 opacity-40 grayscale ring-1 ring-zinc-800",
            )}
            style={
              active
                ? {
                    boxShadow: `0 0 14px ${channel.brandColor}55`,
                  }
                : undefined
            }
          >
            <ChannelBrandIcon channelId={channel.id} className={cn(icon, "rounded-full")} />
            {active && status?.telegram_username && channel.id === "telegram" ? (
              <span className="sr-only">@{status.telegram_username}</span>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}
