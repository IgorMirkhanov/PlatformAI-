"use client";

import { cn } from "@/lib/utils";
import { OMNICHANNEL_DEFINITIONS } from "@/types/channels";
import type { ChannelIntegrationType } from "@/types/channels";

const CHANNEL_SHORT_LABELS: Record<ChannelIntegrationType, string> = {
  telegram: "TG",
  whatsapp: "WA",
  instagram: "IG",
  vkontakte: "VK",
  web_widget: "WEB",
};

interface OmnichannelBarProps {
  connectedChannels: string[];
  className?: string;
}

export function OmnichannelBar({ connectedChannels, className }: OmnichannelBarProps) {
  const connectedSet = new Set(connectedChannels);

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {OMNICHANNEL_DEFINITIONS.map((channel) => {
        const active = connectedSet.has(channel.id);

        return (
          <span
            key={channel.id}
            title={channel.title}
            className={cn(
              "inline-flex h-8 min-w-[2rem] items-center justify-center rounded-lg border px-2 text-[10px] font-bold tracking-wide transition",
              active
                ? cn("border-transparent text-white", channel.buttonGlow)
                : "border-zinc-800 bg-zinc-950/80 text-zinc-600",
            )}
            style={
              active
                ? {
                    backgroundColor: `${channel.brandColor}22`,
                    boxShadow: `0 0 16px ${channel.brandColor}55`,
                    color: channel.brandColor,
                  }
                : undefined
            }
          >
            {CHANNEL_SHORT_LABELS[channel.id]}
          </span>
        );
      })}
    </div>
  );
}
