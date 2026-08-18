"use client";

import { CrmIntegrationHub } from "@/components/integrations/CrmIntegrationHub";
import type { BotAgentProfile } from "@/types/agent";

interface AgentIntegrationsTabProps {
  botId: string;
  profile: BotAgentProfile;
}

export function AgentIntegrationsTab({ botId, profile }: AgentIntegrationsTabProps) {
  return <CrmIntegrationHub botId={botId} profile={profile} />;
}
