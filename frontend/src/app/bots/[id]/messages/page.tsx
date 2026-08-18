"use client";

import { useParams } from "next/navigation";

import { AgentMessagesTab } from "@/components/bots/AgentMessagesTab";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

export default function AgentMessagesPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;

  return <AgentMessagesTab botId={botId} profile={profile} />;
}
