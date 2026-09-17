"use client";

import { useParams } from "next/navigation";

import { AgentControlTab } from "@/components/bots/AgentControlTab";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

export default function AgentControlPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) {
    return (
      <div className="moonai-panel text-center text-sm text-[var(--canvas-muted)]">
        Профиль агента недоступен.
      </div>
    );
  }

  return <AgentControlTab botId={botId} profile={profile} />;
}
