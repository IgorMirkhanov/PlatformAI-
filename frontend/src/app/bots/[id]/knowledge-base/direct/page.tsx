"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { AgentKnowledgeBaseTab } from "@/components/bots/AgentKnowledgeBaseTab";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";

export default function DirectRagPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;

  return (
    <div className="space-y-5">
      <Link
        href={`/bots/${botId}/knowledge-base`}
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-200"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        К выбору типа RAG
      </Link>
      <div>
        <h2 className="text-lg font-semibold text-zinc-50">Прямой RAG</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Заполните данные вручную. ИИ проходит по всему массиву знаний при каждом ответе.
        </p>
      </div>
      <AgentKnowledgeBaseTab botId={botId} profile={profile} mode="direct" />
    </div>
  );
}
