"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  Braces,
  Cpu,
  MessageSquare,
  MessagesSquare,
  Plug,
  Radio,
  Settings,
  Sparkles,
} from "lucide-react";

import { OmnichannelStatusStrip } from "@/components/channels/OmnichannelStatusStrip";
import {
  AGENT_TABS,
  getActiveAgentTabFromPath,
  getAgentTabPath,
  getAgentTestChatPath,
  isAgentTestChatPath,
} from "@/lib/agent-routes";
import { canAccessAgentTab } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import type { AgentTabId, BotAgentProfile } from "@/types/agent";

const TAB_ICONS: Record<AgentTabId, LucideIcon> = {
  settings: Settings,
  prompting: Sparkles,
  messages: MessagesSquare,
  "llm-models": Cpu,
  functions: Braces,
  "knowledge-base": BookOpen,
  integrations: Plug,
  channels: Radio,
};

import { mergeChannelStatuses } from "@/types/channels";

const TAB_PAGE_TITLES: Partial<Record<AgentTabId, string>> = {
  settings: "Настройки агента",
  channels: "Каналы",
  integrations: "Интеграции",
  prompting: "Промптинг",
};

const TAB_DESCRIPTIONS: Record<AgentTabId, string> = {
  settings: "Общие параметры профиля, статус и расписание работы.",
  prompting: "Системные инструкции, переменные контекста и RAG.",
  messages: "Шаблоны сообщений и параметры доставки.",
  "llm-models": "Выбор модели, температура и лимиты токенов.",
  functions: "Пользовательский код и расширения сценария.",
  "knowledge-base": "Документы и контекст для ответов агента.",
  integrations: "CRM и внешние сервисы для автоматизации продаж.",
  channels: "Omnichannel-точки входа: мессенджеры и виджет сайта.",
};

interface AgentWorkspaceHeaderProps {
  botId: string;
  profile: BotAgentProfile;
}

export function AgentWorkspaceHeader({ botId, profile }: AgentWorkspaceHeaderProps) {
  const pathname = usePathname();
  const currentUser = useBotStore((state) => state.currentUser);
  const channelStatuses = useBotStore((state) => state.channelStatuses[botId]);
  const userRole = currentUser?.role;
  const isTestChat = isAgentTestChatPath(pathname);
  const activeTab = getActiveAgentTabFromPath(pathname) ?? "settings";
  const activeTabMeta = AGENT_TABS.find((tab) => tab.id === activeTab) ?? AGENT_TABS[0];
  const pageTitle = TAB_PAGE_TITLES[activeTabMeta.id] ?? activeTabMeta.label;
  const visibleTabs = AGENT_TABS.filter((tab) => canAccessAgentTab(userRole, tab.id));
  const channelMap = channelStatuses ?? mergeChannelStatuses([]);

  if (isTestChat) {
    return (
      <header className="mb-6 border-b border-zinc-800/80 pb-5">
        <nav className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
          <Link href="/dashboard" className="transition hover:text-zinc-300">
            ИИ Агенты
          </Link>
          <span>/</span>
          <span className="text-zinc-300">{profile.name}</span>
          <span>/</span>
          <span className="text-violet-300">Тестовый чат</span>
        </nav>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Тестовый чат</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Песочница с трассировкой выполнения для {profile.name}.
        </p>
      </header>
    );
  }

  return (
    <header className="mb-8">
      <nav className="mb-4 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
        <Link href="/dashboard" className="transition hover:text-zinc-300">
          ИИ Агенты
        </Link>
        <span>/</span>
        <span className="truncate text-zinc-300">{profile.name}</span>
        <span>/</span>
        <span className="text-violet-300">{activeTabMeta.label}</span>
      </nav>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">{pageTitle}</h1>
          <p className="mt-1 text-sm text-zinc-500">{TAB_DESCRIPTIONS[activeTabMeta.id]}</p>
        </div>

        <div className="flex flex-col items-end gap-3">
          <OmnichannelStatusStrip statuses={channelMap} size="md" />
        </div>
      </div>

      <div className="relative -mx-1 overflow-x-auto pb-1">
        <div className="flex min-w-max items-center gap-1 border-b border-zinc-800/80 px-1">
          {visibleTabs.map((tab) => {
            const href = getAgentTabPath(botId, tab.id);
            const isActive = activeTab === tab.id;
            const Icon = TAB_ICONS[tab.id];

            return (
              <Link
                key={tab.id}
                href={href}
                className={cn(
                  "group relative inline-flex items-center gap-2 px-3 py-3 text-sm font-medium transition",
                  isActive ? "text-violet-300" : "text-zinc-500 hover:text-zinc-200",
                )}
              >
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    isActive ? "text-violet-400" : "text-zinc-600 group-hover:text-zinc-400",
                  )}
                />
                {tab.label}
                {isActive && (
                  <span className="absolute inset-x-1 bottom-0 h-0.5 rounded-full bg-violet-500" />
                )}
              </Link>
            );
          })}
          <Link
            href={getAgentTestChatPath(botId)}
            className={cn(
              "group relative inline-flex items-center gap-2 px-3 py-3 text-sm font-medium transition",
              isTestChat ? "text-violet-300" : "text-zinc-500 hover:text-zinc-200",
            )}
          >
            <MessageSquare
              className={cn(
                "h-4 w-4 shrink-0",
                isTestChat ? "text-violet-400" : "text-zinc-600 group-hover:text-zinc-400",
              )}
            />
            Тестовый чат
            {isTestChat && (
              <span className="absolute inset-x-1 bottom-0 h-0.5 rounded-full bg-violet-500" />
            )}
          </Link>
        </div>
      </div>
    </header>
  );
}
