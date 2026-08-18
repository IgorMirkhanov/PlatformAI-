"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, Loader2, Radio } from "lucide-react";

import { ChannelHubContext } from "@/components/channel-hub/ChannelHubContext";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import { fetchHubChannels } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  HUB_CHANNEL_NAV,
  mergeHubStatuses,
  type HubChannelStatusItem,
  type HubChannelType,
} from "@/types/channel-hub";

interface ChannelsAgentLayoutProps {
  children: ReactNode;
}

export default function ChannelsAgentLayout({ children }: ChannelsAgentLayoutProps) {
  const params = useParams<{ id: string }>();
  const pathname = usePathname();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  const [statuses, setStatuses] = useState<Record<HubChannelType, HubChannelStatusItem> | null>(
    null,
  );
  const [hubLoading, setHubLoading] = useState(true);

  const refreshStatuses = useCallback(async () => {
    try {
      const response = await fetchHubChannels(botId);
      setStatuses(mergeHubStatuses(response.channels));
    } catch {
      setStatuses(mergeHubStatuses([]));
    } finally {
      setHubLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    void refreshStatuses();
  }, [refreshStatuses]);

  const connectedCount = useMemo(
    () => Object.values(statuses ?? {}).filter((item) => item.connected).length,
    [statuses],
  );

  const contextValue = useMemo(() => {
    if (!statuses) return null;
    return { botId, statuses, refreshStatuses };
  }, [botId, statuses, refreshStatuses]);

  return (
    // Fill AppShell scroll host; clip here so only the panel <section> scrolls.
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col px-4 py-5 lg:px-8 lg:py-6">
        <header className="mb-5 flex shrink-0 flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Link
              href={`/bots/${botId}/settings`}
              className="mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/80 text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 ring-1 ring-emerald-500/25">
                <Radio className="h-5 w-5 text-emerald-400" />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
                  Каналы
                </p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-50">
                  {loading && !profile ? "Загрузка…" : profile?.name ?? "Агент"}
                </h1>
                <p className="mt-1 max-w-xl text-sm text-zinc-500">
                  Omnichannel Integration Hub — подключите мессенджеры и соцсети для входящих
                  диалогов.
                </p>
              </div>
            </div>
          </div>
          <div className="rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/90 px-4 py-3 text-right backdrop-blur-xl">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Активные каналы</p>
            <p className="mt-1 text-lg font-semibold text-zinc-100">
              {hubLoading ? "…" : `${connectedCount} / ${HUB_CHANNEL_NAV.length}`}
            </p>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 gap-6 overflow-hidden">
          <aside className="hidden w-[240px] shrink-0 overflow-y-auto rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/90 p-3 backdrop-blur-xl lg:block">
            <nav className="space-y-1">
              {HUB_CHANNEL_NAV.map((item) => {
                const href = `/dashboard/channels-agent/${botId}/${item.href}`;
                const active = pathname === href || pathname.startsWith(`${href}/`);
                const status = statuses?.[item.id];
                const connected = Boolean(status?.connected);

                return (
                  <Link
                    key={item.id}
                    href={href}
                    className={cn(
                      "group flex items-center gap-3 rounded-xl px-3 py-2.5 transition",
                      active
                        ? "bg-zinc-900/90 ring-1 ring-zinc-700/80"
                        : "hover:bg-zinc-900/50",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold",
                        connected
                          ? "text-white"
                          : "bg-zinc-950 text-zinc-600 ring-1 ring-zinc-800",
                      )}
                      style={
                        connected
                          ? {
                              backgroundColor: `${item.accent}22`,
                              boxShadow: `0 0 14px ${item.accent}55`,
                              color: item.accent,
                            }
                          : undefined
                      }
                    >
                      {item.shortLabel}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-zinc-200">
                        {item.label}
                      </span>
                      <span className="block truncate text-[11px] text-zinc-500">
                        {connected ? "Подключён" : item.description}
                      </span>
                    </span>
                  </Link>
                );
              })}
            </nav>
          </aside>

          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {/* Mobile channel strip — horizontal only, not a nested vertical scroller */}
            <div className="mb-3 flex shrink-0 gap-2 overflow-x-auto pb-1 lg:hidden">
              {HUB_CHANNEL_NAV.map((item) => {
                const href = `/dashboard/channels-agent/${botId}/${item.href}`;
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    key={item.id}
                    href={href}
                    className={cn(
                      "shrink-0 rounded-lg border px-3 py-1.5 text-xs font-medium",
                      active
                        ? "border-zinc-600 bg-zinc-900 text-zinc-100"
                        : "border-zinc-800 text-zinc-500",
                    )}
                  >
                    {item.shortLabel}
                  </Link>
                );
              })}
            </div>

            <section className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6">
              {hubLoading && !contextValue ? (
                <div className="flex min-h-[16rem] items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/50">
                  <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
                </div>
              ) : contextValue ? (
                <ChannelHubContext.Provider value={contextValue}>
                  {children}
                </ChannelHubContext.Provider>
              ) : null}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
