"use client";

import {
  Globe,
  Instagram,
  MessageCircle,
  Send,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { PlatformType } from "@/types/inbox";

const PLATFORM_META: Record<
  PlatformType,
  { label: string; className: string; Icon: typeof Send }
> = {
  TELEGRAM: {
    label: "Telegram",
    className: "bg-sky-500/15 text-sky-400 ring-sky-500/30",
    Icon: Send,
  },
  WHATSAPP: {
    label: "WhatsApp",
    className: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
    Icon: MessageCircle,
  },
  INSTAGRAM: {
    label: "Instagram",
    className: "bg-fuchsia-500/15 text-fuchsia-400 ring-fuchsia-500/30",
    Icon: Instagram,
  },
  VKONTAKTE: {
    label: "VK",
    className: "bg-blue-500/15 text-blue-400 ring-blue-500/30",
    Icon: MessageCircle,
  },
  WEB_WIDGET: {
    label: "Web",
    className: "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30",
    Icon: Globe,
  },
};

interface ChannelIndicatorProps {
  platform: PlatformType;
  size?: "sm" | "md";
  showLabel?: boolean;
  className?: string;
}

export function ChannelIndicator({
  platform,
  size = "sm",
  showLabel = false,
  className,
}: ChannelIndicatorProps) {
  const meta = PLATFORM_META[platform] ?? PLATFORM_META.TELEGRAM;
  const Icon = meta.Icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full ring-1 ring-inset",
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-xs",
        meta.className,
        className,
      )}
      title={meta.label}
    >
      <Icon className={cn(size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5")} />
      {showLabel ? meta.label : null}
    </span>
  );
}

export function getPlatformLabel(platform: PlatformType): string {
  return PLATFORM_META[platform]?.label ?? platform;
}
