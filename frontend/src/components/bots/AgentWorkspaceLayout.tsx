"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";

import { AgentWorkspaceHeader } from "@/components/bots/AgentWorkspaceHeader";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import { useResolvedBotId } from "@/hooks/useResolvedBotId";
import { useBotStore } from "@/store/useBotStore";
import type { BotAgentProfile } from "@/types/agent";

interface AgentWorkspaceContextValue {
  botId: string;
  profile: BotAgentProfile;
}

const AgentWorkspaceContext = createContext<AgentWorkspaceContextValue | null>(null);

export function useAgentWorkspaceContext(): AgentWorkspaceContextValue {
  const ctx = useContext(AgentWorkspaceContext);
  if (!ctx) {
    throw new Error("useAgentWorkspaceContext must be used within AgentWorkspaceLayout");
  }
  return ctx;
}

interface AgentWorkspaceLayoutProps {
  children: ReactNode;
  emptyMessage?: string;
}

export function AgentWorkspaceLayout({
  children,
  emptyMessage = "Создайте агента, чтобы открыть рабочую область.",
}: AgentWorkspaceLayoutProps) {
  const botId = useResolvedBotId(true);
  const loadBotChannels = useBotStore((state) => state.loadBotChannels);
  const { profile, loading } = useAgentWorkspace(botId ?? "");

  useEffect(() => {
    if (botId) {
      void loadBotChannels(botId);
    }
  }, [botId, loadBotChannels]);

  if (!botId) {
    return (
      <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 lg:px-8">
        <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-16 text-center">
          <p className="text-sm text-zinc-400">{emptyMessage}</p>
        </div>
      </div>
    );
  }

  if (loading && !profile) {
    return (
      <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 lg:px-8">
        <PageSkeleton />
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 lg:px-8">
        <div className="moonai-panel text-center">
          <p className="text-sm text-zinc-400">Профиль агента недоступен.</p>
        </div>
      </div>
    );
  }

  return (
    <AgentWorkspaceContext.Provider value={{ botId, profile }}>
      <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 lg:px-8">
        <AgentWorkspaceHeader botId={botId} profile={profile} />
        {children}
      </div>
    </AgentWorkspaceContext.Provider>
  );
}
