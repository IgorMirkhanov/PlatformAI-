"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Loader2, Workflow } from "lucide-react";

import { ApiError } from "@/lib/api";
import { createFlow } from "@/lib/flow/api";
import { FLOW_TEMPLATES } from "@/lib/flow-templates";
import { getAgentTabPath } from "@/lib/agent-routes";
import { DEFAULT_NEW_AGENT_NAME, provisionNewAgent } from "@/lib/provision-agent";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import {
  AGENT_USE_CASE_TEMPLATES,
  type AgentUseCaseTemplateId,
} from "@/types/agent-templates";

export default function TemplatesGalleryPage() {
  const router = useRouter();
  const { showToast } = useToast();
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const loadAgentProfile = useBotStore((state) => state.loadAgentProfile);

  const [agentName, setAgentName] = useState(DEFAULT_NEW_AGENT_NAME);
  const [creatingAgent, setCreatingAgent] = useState<AgentUseCaseTemplateId | null>(null);
  const [creatingFlow, setCreatingFlow] = useState<string | null>(null);

  const onCreateAgent = async (useCase: AgentUseCaseTemplateId) => {
    const name = agentName.trim() || DEFAULT_NEW_AGENT_NAME;
    setCreatingAgent(useCase);
    try {
      const { botId } = await provisionNewAgent(name, useCase);
      setActiveBotId(botId);
      await loadAgentProfile(botId);
      showToast("Агент создан из шаблона.", "success");
      router.push(getAgentTabPath(botId, "settings"));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать агента."), "error");
      setCreatingAgent(null);
    }
  };

  const onCreateFlow = async (templateId: string) => {
    const template = FLOW_TEMPLATES.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    setCreatingFlow(templateId);
    try {
      const flow = await createFlow({
        name: template.name,
        nodes: template.nodes,
        edges: template.edges,
      });
      showToast("Сценарий создан из шаблона.", "success");
      router.push(`/dashboard/flows/${flow.id}`);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Не удалось создать flow.", "error");
      setCreatingFlow(null);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Шаблоны</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Готовые агенты и графы Flow Builder. Можно сразу создать рабочую копию.
        </p>
      </div>

      <section className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-medium text-zinc-100">Агенты</h2>
          <label className="block text-xs text-zinc-500">
            Имя нового агента
            <input
              value={agentName}
              onChange={(event) => setAgentName(event.target.value)}
              className="mt-1 w-64 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
          </label>
        </div>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {AGENT_USE_CASE_TEMPLATES.map((template) => (
            <li
              key={template.id}
              className="flex flex-col rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-4"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/10">
                <Bot className="h-4 w-4 text-violet-400" />
              </div>
              <h3 className="mt-3 text-sm font-medium text-zinc-100">{template.label}</h3>
              <p className="mt-1 flex-1 text-xs text-zinc-500">{template.description}</p>
              <button
                type="button"
                disabled={creatingAgent !== null}
                onClick={() => void onCreateAgent(template.id)}
                className={cn(
                  "mt-4 inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-3 py-2 text-xs font-semibold text-white",
                  "hover:bg-violet-500 disabled:opacity-60",
                )}
              >
                {creatingAgent === template.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Создать агента
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-medium text-zinc-100">Сценарии Flow</h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {FLOW_TEMPLATES.map((template) => (
            <li
              key={template.id}
              className="flex flex-col rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-4"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
                <Workflow className="h-4 w-4 text-emerald-400" />
              </div>
              <h3 className="mt-3 text-sm font-medium text-zinc-100">{template.name}</h3>
              <p className="mt-1 flex-1 text-xs text-zinc-500">{template.description}</p>
              <p className="mt-2 text-[11px] text-zinc-600">
                {template.nodes.length} узлов · {template.edges.length} связей
              </p>
              <button
                type="button"
                disabled={creatingFlow !== null}
                onClick={() => void onCreateFlow(template.id)}
                className={cn(
                  "mt-4 inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-100",
                  "hover:bg-zinc-800 disabled:opacity-60",
                )}
              >
                {creatingFlow === template.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Создать flow
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
