"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bot, Settings2 } from "lucide-react";

import { CreateAgentButton } from "@/components/layout/CreateAgentButton";
import { Toggle } from "@/components/ui/Toggle";
import { ApiError, updateBotSettings } from "@/lib/api";
import { getAgentTabPath } from "@/lib/agent-routes";
import { formatNumber } from "@/lib/dashboard-utils";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useBotStore } from "@/store/useBotStore";
import type { AgentStatusSummary } from "@/types/dashboard";

interface AgentsGridProps {
  agents: AgentStatusSummary[];
  onRefresh?: () => void;
}

function formatCreatedLabel(botId: string): string {
  const hash = botId.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const daysAgo = hash % 14;
  if (daysAgo === 0) return "Создан сегодня";
  if (daysAgo === 1) return "Создан вчера";
  return `Создан ${daysAgo} дн. назад`;
}

export function AgentsGrid({ agents, onRefresh }: AgentsGridProps) {
  const router = useRouter();
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const setAgentProfile = useBotStore((state) => state.setAgentProfile);
  const activeBotId = useBotStore((state) => state.activeBotId);
  const { showToast } = useToast();

  const openAgent = (botId: string): void => {
    setActiveBotId(botId);
    router.push(getAgentTabPath(botId, "settings"));
  };

  const handleToggle = async (
    agent: AgentStatusSummary,
    isActive: boolean,
  ): Promise<void> => {
    try {
      const profile = await updateBotSettings(agent.bot_id, { is_active: isActive });
      setAgentProfile(profile);
      showToast(`${agent.bot_name} ${isActive ? "активирован" : "остановлен"}.`, "success");
      onRefresh?.();
    } catch (error) {
      showToast(
        error instanceof ApiError ? error.message : "Не удалось обновить статус агента.",
        "error",
      );
    }
  };

  if (agents.length === 0) {
    return (
      <div className="luxury-card text-center">
        <p className="text-sm text-zinc-500">
          Агенты не найдены. Создайте первого агента — откроется экран настроек.
        </p>
        <CreateAgentButton variant="button" label="Создать агента" className="mt-4" />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800/60 bg-[#121214]">
      <div className="grid grid-cols-[1.4fr_1fr_0.8fr_0.8fr_auto] gap-4 border-b border-zinc-800/60 px-5 py-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-600 max-lg:hidden">
        <span>Агент</span>
        <span>Создан</span>
        <span>Диалоги</span>
        <span>Статус</span>
        <span className="text-right">Действия</span>
      </div>

      <ul className="divide-y divide-zinc-800/60">
        {agents.map((agent) => (
          <li
            key={agent.bot_id}
            role="button"
            tabIndex={0}
            onClick={() => openAgent(agent.bot_id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openAgent(agent.bot_id);
              }
            }}
            className={cn(
              "grid cursor-pointer gap-4 px-5 py-4 transition hover:bg-zinc-900/40 max-lg:space-y-3 lg:grid-cols-[1.4fr_1fr_0.8fr_0.8fr_auto] lg:items-center",
              activeBotId === agent.bot_id && "bg-indigo-500/5 ring-1 ring-inset ring-indigo-500/20",
            )}
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/10 ring-1 ring-indigo-500/20">
                <Bot className="h-4 w-4 text-indigo-400" />
              </div>
              <div>
                <p className="text-sm font-semibold text-zinc-100">{agent.bot_name}</p>
                <p className="text-xs text-zinc-500">{agent.platform_type}</p>
              </div>
            </div>

            <p className="text-xs text-zinc-400">{formatCreatedLabel(agent.bot_id)}</p>

            <p className="text-sm font-medium text-zinc-200">
              {formatNumber(agent.unique_dialogs)}
            </p>

            <div className="flex items-center gap-3" onClick={(event) => event.stopPropagation()}>
              <Toggle
                checked={agent.is_active}
                onChange={(checked) => void handleToggle(agent, checked)}
              />
              <span
                className={cn(
                  "text-xs font-medium",
                  agent.is_active ? "text-emerald-400" : "text-zinc-500",
                )}
              >
                {agent.is_active ? "Активен" : "Пауза"}
              </span>
            </div>

            <div
              className="flex flex-wrap justify-start gap-2 lg:justify-end"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                onClick={() => openAgent(agent.bot_id)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800/50 hover:text-white"
              >
                <Settings2 className="h-3.5 w-3.5" />
                Настройки
              </button>
              <Link
                href={`/flow-builder?botId=${agent.bot_id}`}
                className="inline-flex rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20"
              >
                Сценарий
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
