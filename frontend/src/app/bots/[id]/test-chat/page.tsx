"use client";

import { useCallback, useState } from "react";
import { useParams } from "next/navigation";

import { NeuralTraceExplorer } from "@/components/sandbox/NeuralTraceExplorer";
import { TestChatPanel } from "@/components/sandbox/TestChatPanel";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import type { ExecutionTrace, SandboxRuntimeLog } from "@/types/sandbox";
import { createEmptyTrace } from "@/types/sandbox";

export default function AgentTestChatPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  const [activeTrace, setActiveTrace] = useState<ExecutionTrace>(createEmptyTrace());
  const [runtimeLogs, setRuntimeLogs] = useState<SandboxRuntimeLog[]>([]);

  const handleTraceChange = useCallback((trace: ExecutionTrace) => {
    setActiveTrace(trace);
  }, []);

  const handleRuntimeLogsChange = useCallback((logs: SandboxRuntimeLog[]) => {
    setRuntimeLogs(logs);
  }, []);

  if (loading && !profile) {
    return <PageSkeleton />;
  }

  if (!profile) {
    return null;
  }

  return (
    <div className="flex min-h-[calc(100vh-7rem)] flex-col">
      <header className="mb-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
          Agent Workspace · Sandbox
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-zinc-50">Тестовый чат</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Внутренний симулятор для {profile.name} без записи в production-диалоги.
        </p>
      </header>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <TestChatPanel
          botId={botId}
          botName={profile.name}
          onTraceChange={handleTraceChange}
          onRuntimeLogsChange={handleRuntimeLogsChange}
        />
        <NeuralTraceExplorer trace={activeTrace} runtimeLogs={runtimeLogs} />
      </div>
    </div>
  );
}
