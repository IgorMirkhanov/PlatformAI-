"use client";

import { useParams } from "next/navigation";

import { KnowledgeRagPicker } from "@/components/knowledge/KnowledgeRagPicker";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

export default function AgentKnowledgeBasePage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;

  return <KnowledgeRagPicker botId={botId} />;
}
