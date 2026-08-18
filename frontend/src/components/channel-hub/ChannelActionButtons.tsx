"use client";

import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface ChannelActionButtonsProps {
  isPending: boolean;
  /** @deprecated Prefer canConnect / canDisconnect — kept for older channel pages. */
  connected?: boolean;
  canConnect?: boolean;
  canDisconnect?: boolean;
  connectLabel?: string;
  disconnectLabel?: string;
  onConnect?: () => void;
  onDisconnect?: () => void;
  connectClassName?: string;
  extra?: ReactNode;
}

export function ChannelActionButtons({
  isPending,
  connected,
  canConnect = connected === undefined ? true : !connected,
  canDisconnect = connected === undefined ? false : connected,
  connectLabel = "Подключить",
  disconnectLabel = "Отключить",
  onConnect,
  onDisconnect,
  connectClassName,
  extra,
}: ChannelActionButtonsProps) {
  return (
    <div className="flex flex-wrap gap-2 pt-2">
      {onConnect ? (
        <button
          type="button"
          disabled={isPending || !canConnect}
          aria-busy={isPending}
          onClick={onConnect}
          className={cn(
            "inline-flex min-h-[2.75rem] items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50",
            connectClassName,
          )}
        >
          {isPending ? <Loader2 className="h-4 w-4 shrink-0 animate-spin" /> : null}
          <span>{isPending ? "Сохранение…" : connectLabel}</span>
        </button>
      ) : null}
      {onDisconnect ? (
        <button
          type="button"
          disabled={isPending || !canDisconnect}
          aria-busy={isPending}
          onClick={onDisconnect}
          className="inline-flex min-h-[2.75rem] items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-2.5 text-sm font-medium text-zinc-300 transition hover:border-zinc-600 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isPending ? <Loader2 className="h-4 w-4 shrink-0 animate-spin" /> : null}
          <span>{isPending ? "Сохранение…" : disconnectLabel}</span>
        </button>
      ) : null}
      {extra}
    </div>
  );
}
