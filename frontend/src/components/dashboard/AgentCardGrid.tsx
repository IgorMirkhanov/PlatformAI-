"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, type Variants } from "framer-motion";
import { Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { AgentCardActions } from "@/components/bots/AgentCardActions";
import { OmnichannelBar } from "@/components/dashboard/OmnichannelBar";
import { Toggle } from "@/components/ui/Toggle";
import { getAgentTabPath } from "@/lib/agent-routes";
import { updateBotSettings } from "@/lib/api";
import { formatNumber } from "@/lib/dashboard-utils";
import { useAsyncAction } from "@/lib/hooks/use-async-action";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { AVATAR_PRESETS } from "@/types/agent";
import type { AgentStatusSummary } from "@/types/dashboard";

interface AgentCardGridProps {
  agents: AgentStatusSummary[];
  onRefresh?: () => void;
}

function avatarForBot(botId: string): string {
  const hash = botId.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return AVATAR_PRESETS[hash % AVATAR_PRESETS.length];
}

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 18, scale: 0.98 },
  visible: (index: number) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { delay: index * 0.06, duration: 0.35, ease: "easeOut" },
  }),
};

function AgentCard({
  agent,
  index,
  avatar,
  onRefresh,
  onOpen,
}: {
  agent: AgentStatusSummary;
  index: number;
  avatar: string;
  onRefresh?: () => void;
  onOpen: (botId: string) => void;
}) {
  const setAgentProfile = useBotStore((state) => state.setAgentProfile);
  const [isActive, setIsActive] = useState(agent.is_active);
  const connectedChannels = agent.connected_channels ?? [];

  useEffect(() => {
    setIsActive(agent.is_active);
  }, [agent.is_active, agent.bot_id]);

  const persistActive = useCallback(
    async (next: boolean) => {
      const profile = await updateBotSettings(agent.bot_id, { is_active: next });
      setAgentProfile(profile);
      onRefresh?.();
      return profile;
    },
    [agent.bot_id, onRefresh, setAgentProfile],
  );

  const { run, isPending } = useAsyncAction(persistActive, {
    successMessage: false,
    errorMessage: "Не удалось обновить статус агента.",
  });

  const handleChange = async (next: boolean) => {
    const previous = isActive;
    setIsActive(next);
    const result = await run(next);
    if (!result.ok) {
      setIsActive(previous);
    }
  };

  return (
    <motion.article
      custom={index}
      variants={cardVariants}
      initial="hidden"
      animate="visible"
      className="group relative overflow-hidden rounded-2xl border border-zinc-800/80 bg-gradient-to-br from-[#121214] via-[#0f0f11] to-black p-5 transition hover:border-violet-500/25 hover:shadow-glow-purple"
    >
      <div className="pointer-events-none absolute -right-10 -top-10 h-28 w-28 rounded-full bg-violet-500/5 blur-2xl transition group-hover:bg-violet-500/10" />

      <div className="flex items-start gap-4">
        <div className="relative shrink-0">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-zinc-700 via-zinc-900 to-black text-3xl ring-2 ring-zinc-700/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
            {avatar}
          </div>
          <span
            className={cn(
              "absolute -bottom-1 -right-1 h-3.5 w-3.5 rounded-full ring-2 ring-[#121214]",
              isActive ? "bg-emerald-400" : "bg-zinc-600",
            )}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-zinc-100">{agent.bot_name}</h3>
              <p className="mt-0.5 text-xs text-zinc-500">{agent.platform_type}</p>
            </div>
            <AgentCardActions
              botId={agent.bot_id}
              botName={agent.bot_name}
              onRefresh={onRefresh}
            />
          </div>
          <p className="mt-2 text-xs text-zinc-400">
            {formatNumber(agent.unique_dialogs)} диалогов
          </p>
        </div>
      </div>

      <div className="mt-5">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
          Каналы
        </p>
        <OmnichannelBar connectedChannels={connectedChannels} />
      </div>

      <div
        className="mt-5 rounded-xl border border-zinc-800/80 bg-black/20 px-3 py-3"
        onClick={(event) => event.stopPropagation()}
      >
        <Toggle
          checked={isActive}
          onChange={(value) => void handleChange(value)}
          isLoading={isPending}
          label="Статус бота"
          description={isActive ? "Активен в мессенджерах" : "Ответы приостановлены"}
        />
      </div>

      <div className="mt-5 flex items-center gap-2">
        <Button
          type="button"
          className="flex-1 bg-gradient-to-r from-violet-600 to-indigo-600 text-white hover:from-violet-500 hover:to-indigo-500 disabled:bg-gradient-to-r disabled:from-violet-600 disabled:to-indigo-600"
          onClick={() => onOpen(agent.bot_id)}
        >
          <Settings2 className="h-4 w-4" />
          Управление
        </Button>
      </div>
    </motion.article>
  );
}

export function AgentCardGrid({ agents, onRefresh }: AgentCardGridProps) {
  const router = useRouter();
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const avatarByBotId = useBotStore((state) => state.avatarByBotId);

  const openAgent = (botId: string): void => {
    setActiveBotId(botId);
    router.push(getAgentTabPath(botId, "settings"));
  };

  if (agents.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-[#121214]/60 px-6 py-14 text-center">
        <p className="text-sm text-zinc-500">
          Агенты не найдены. Создайте первого ИИ-агента, чтобы начать работу.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {agents.map((agent, index) => (
        <AgentCard
          key={agent.bot_id}
          agent={agent}
          index={index}
          avatar={avatarByBotId[agent.bot_id] ?? avatarForBot(agent.bot_id)}
          onRefresh={onRefresh}
          onOpen={openAgent}
        />
      ))}
    </div>
  );
}
