"use client";



import { useParams } from "next/navigation";



import { AgentPromptingTab } from "@/components/bots/AgentPromptingTab";

import { PageSkeleton } from "@/components/ui/Skeleton";

import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";



export default function AgentPromptingPage() {

  const params = useParams<{ id: string }>();

  const botId = params.id;

  const { profile, loading } = useAgentWorkspace(botId);



  if (loading && !profile) return <PageSkeleton />;

  if (!profile) return null;



  return <AgentPromptingTab botId={botId} profile={profile} />;

}


