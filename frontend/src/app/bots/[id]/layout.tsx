"use client";



import { useParams, usePathname } from "next/navigation";

import { useEffect } from "react";



import { AgentWorkspaceHeader } from "@/components/bots/AgentWorkspaceHeader";

import { PageSkeleton } from "@/components/ui/Skeleton";

import { isAgentTestChatPath } from "@/lib/agent-routes";

import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

import { useBotStore } from "@/store/useBotStore";



export default function BotWorkspaceLayout({ children }: { children: React.ReactNode }) {

  const params = useParams<{ id: string }>();

  const pathname = usePathname();

  const botId = params.id;

  const isTestChat = isAgentTestChatPath(pathname);

  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const loadBotChannels = useBotStore((state) => state.loadBotChannels);

  const { profile, loading } = useAgentWorkspace(botId);

  useEffect(() => {
    setActiveBotId(botId);
  }, [botId, setActiveBotId]);

  useEffect(() => {
    void loadBotChannels(botId);
  }, [botId, loadBotChannels]);

  if (loading && !profile) {

    return (

      <div className="mx-auto max-w-7xl px-4 py-8 lg:px-8">

        <PageSkeleton />

      </div>

    );

  }



  if (!profile) {

    return (

      <div className="mx-auto max-w-7xl px-4 py-10 lg:px-8">

        <div className="moonai-panel text-center">

          <p className="text-sm text-zinc-400">Профиль агента недоступен.</p>

          <p className="mt-1 text-xs text-zinc-500">

            Проверьте backend или выберите другого агента в боковой панели.

          </p>

        </div>

      </div>

    );

  }



  return (

    <div

      className={

        isTestChat

          ? "mx-auto max-w-[1600px] px-4 pb-10 pt-6 lg:px-8"

          : "mx-auto max-w-7xl px-4 pb-10 pt-6 lg:px-8"

      }

    >

      <AgentWorkspaceHeader botId={botId} profile={profile} />

      {children}

    </div>

  );

}


