"use client";

import { useParams } from "next/navigation";

import { AgentSettingsTab } from "@/components/bots/AgentSettingsTab";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

export default function AgentSettingsPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;

  return <AgentSettingsTab botId={botId} profile={profile} />;
}
