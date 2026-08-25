"use client";



import Link from "next/link";

import { useParams, usePathname } from "next/navigation";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { ArrowLeft, Loader2 } from "lucide-react";



import { ChannelHubContext } from "@/components/channel-hub/ChannelHubContext";

import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

import { fetchHubChannels } from "@/lib/api";

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



  const isSettingsSubRoute = useMemo(() => {

    return HUB_CHANNEL_NAV.some((item) => pathname.includes(`/${item.href}`));

  }, [pathname]);



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



  const contextValue = useMemo(() => {

    if (!statuses) return null;

    return { botId, statuses, refreshStatuses };

  }, [botId, statuses, refreshStatuses]);



  return (

    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-zinc-950 text-zinc-100">

      <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col px-4 py-5 lg:px-8 lg:py-6">

        {isSettingsSubRoute ? (

          <header className="mb-5 flex shrink-0 items-center gap-3">

            <Link

              href={`/dashboard/channels?botId=${encodeURIComponent(botId)}`}

              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/80 text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200"

            >

              <ArrowLeft className="h-4 w-4" />

            </Link>

            <div>

              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">

                Настройки канала

              </p>

              <h1 className="mt-1 text-xl font-semibold text-zinc-50">

                {loading && !profile ? "Загрузка…" : profile?.name ?? "Агент"}

              </h1>

            </div>

          </header>

        ) : null}



        <section className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6">

          {hubLoading && !contextValue ? (

            <div className="flex min-h-[16rem] items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/50">

              <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />

            </div>

          ) : contextValue ? (

            <ChannelHubContext.Provider value={contextValue}>{children}</ChannelHubContext.Provider>

          ) : null}

        </section>

      </div>

    </div>

  );

}

