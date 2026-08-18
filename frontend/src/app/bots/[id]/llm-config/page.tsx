"use client";



import { useParams } from "next/navigation";



import { AgentLlmTab } from "@/components/bots/AgentLlmTab";

import { PageSkeleton } from "@/components/ui/Skeleton";

import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";



export default function AgentLlmConfigPage() {

  const params = useParams<{ id: string }>();

  const botId = params.id;

  const { profile, loading } = useAgentWorkspace(botId);



  if (loading && !profile) return <PageSkeleton />;

  if (!profile) return null;



  return <AgentLlmTab botId={botId} profile={profile} />;

}


