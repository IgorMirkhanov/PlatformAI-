"use client";

import { ChannelIntegrationHub } from "@/components/channels/ChannelIntegrationHub";
import type { BotAgentProfile } from "@/types/agent";

interface AgentChannelsTabProps {
  botId: string;
  profile: BotAgentProfile;
}

export function AgentChannelsTab({ botId, profile }: AgentChannelsTabProps) {
  return <ChannelIntegrationHub botId={botId} profile={profile} />;
}
