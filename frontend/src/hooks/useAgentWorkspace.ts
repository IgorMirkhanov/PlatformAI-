"use client";

import { useEffect } from "react";

import { useBotStore } from "@/store/useBotStore";
import { getAvatarForBot } from "@/lib/agent-utils";
import type { BotAgentProfile } from "@/types/agent";

interface UseAgentWorkspaceResult {
  botId: string;
  profile: BotAgentProfile | undefined;
  loading: boolean;
  saving: boolean;
  avatar: string;
}

export function useAgentWorkspace(botId: string): UseAgentWorkspaceResult {
  const profile = useBotStore((state) => state.agentProfiles[botId]);
  const loading = useBotStore((state) => state.profileLoading[botId] ?? false);
  const saving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const avatarByBotId = useBotStore((state) => state.avatarByBotId);
  const loadAgentProfile = useBotStore((state) => state.loadAgentProfile);
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);

  useEffect(() => {
    setActiveBotId(botId);
    if (!profile && !loading) {
      void loadAgentProfile(botId);
    }
  }, [botId, profile, loading, loadAgentProfile, setActiveBotId]);

  return {
    botId,
    profile,
    loading,
    saving,
    avatar: avatarByBotId[botId] ?? getAvatarForBot(botId),
  };
}
