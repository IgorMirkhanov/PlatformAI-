"use client";

import type { ReactNode } from "react";

import { HubConnectionBadge } from "@/components/channel-hub/HubConnectionBadge";
import { cn } from "@/lib/utils";
import type { HubChannelStatus, HubChannelStatusItem } from "@/types/channel-hub";

interface ChannelSetupPanelProps {
  title: string;
  subtitle: string;
  accent: string;
  status: HubChannelStatusItem;
  children: ReactNode;
  instructions?: ReactNode;
  error?: string | null;
  className?: string;
}

export function ChannelSetupPanel({
  title,
  subtitle,
  accent,
  status,
  children,
  instructions,
  error,
  className,
}: ChannelSetupPanelProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full max-w-4xl overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50 backdrop-blur-md",
        className,
      )}
    >
      <div
        className="border-b border-zinc-800 px-6 py-5"
        style={{
          background: `linear-gradient(135deg, ${accent}18 0%, transparent 55%)`,
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
              Состояние подключения
            </p>
            <h2 className="mt-2 text-xl font-semibold text-zinc-50">{title}</h2>
            <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>
            {status.reference_id ? (
              <p className="mt-2 text-xs text-zinc-400">
                ID: <span className="text-zinc-200">{status.reference_id}</span>
              </p>
            ) : null}
            {status.webhook_url ? (
              <p className="mt-1 break-all text-[11px] text-zinc-500">
                Webhook: <span className="text-zinc-300">{status.webhook_url}</span>
              </p>
            ) : null}
          </div>
          <HubConnectionBadge status={status.status as HubChannelStatus} />
        </div>
      </div>

      {error ? (
        <div
          role="alert"
          className="border-b border-[#DC143C]/45 bg-[#DC143C]/15 px-6 py-3 text-sm font-medium text-[#FF6B7A]"
        >
          {error}
        </div>
      ) : null}

      <div className="grid gap-0 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div className="space-y-5 border-b border-zinc-800 p-6 lg:border-b-0 lg:border-r lg:border-zinc-800">
          {children}
        </div>
        <div className="bg-zinc-950/40 p-6">
          <h3 className="text-sm font-semibold text-zinc-200">Инструкция</h3>
          <div className="mt-3 space-y-3 text-sm leading-relaxed text-zinc-500">
            {instructions}
          </div>
        </div>
      </div>
    </div>
  );
}
