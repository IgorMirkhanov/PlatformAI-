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
  Shield,
  Sparkles,
  Workflow,
} from "lucide-react";

import { OmnichannelStatusStrip } from "@/components/channels/OmnichannelStatusStrip";
import {
  AGENT_TABS,
  getActiveAgentTabFromPath,
  getAgentTabPath,
  getAgentTestChatPath,
  isAgentTestChatPath,
} from "@/lib/agent-routes";
import { canAccessAgentTab, canAccessSandbox } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import type { AgentTabId, BotAgentProfile } from "@/types/agent";
import { mergeChannelStatuses } from "@/types/channels";

const TAB_ICONS: Record<AgentTabId, LucideIcon> = {
  settings: Settings,
  prompting: Sparkles,
  messages: MessagesSquare,
  "llm-models": Cpu,
  control: Shield,
  functions: Braces,
  "knowledge-base": BookOpen,
  integrations: Plug,
  channels: Radio,
  scenario: Workflow,
};

const TAB_PAGE_TITLES: Partial<Record<AgentTabId, string>> = {
  settings: "Настройки агента",
  channels: "Каналы",
  integrations: "Интеграции",
  prompting: "Промптинг",
  functions: "Функции",
  control: "Контроль",
  messages: "Сообщения",
  scenario: "Сценарий",
};

const TAB_DESCRIPTIONS: Record<AgentTabId, string> = {
  settings: "Общие параметры профиля, статус и расписание работы.",
  prompting: "Системные инструкции, переменные контекста и RAG.",
  messages: "Шаблоны сообщений и параметры доставки.",
  "llm-models": "Выбор модели, температура и лимиты токенов.",
  control: "Статус агента, расписание и флаги безопасности.",
  functions: "Инструменты Function Calling для агента.",
  "knowledge-base": "Документы и контекст для ответов агента.",
  integrations: "CRM и внешние сервисы для автоматизации продаж.",
  channels: "Omnichannel-точки входа: мессенджеры и виджет сайта.",
  scenario: "Визуальный конструктор сценария этого агента.",
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
  const showTestChat = canAccessSandbox(userRole);
  const channelMap = channelStatuses ?? mergeChannelStatuses([]);

  return (
    <header className="mb-8">
      <nav className="mb-4 flex flex-wrap items-center gap-1.5 text-xs text-[var(--canvas-muted)]">
        <Link href="/dashboard" className="transition hover:text-[var(--canvas-fg)]">
          ИИ Агенты
        </Link>
        <span>/</span>
        <span className="truncate text-[var(--canvas-fg)]">{profile.name}</span>
        <span>/</span>
        <span className="text-violet-400">{isTestChat ? "Тестовый чат" : activeTabMeta.label}</span>
      </nav>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--canvas-fg)]">
            {isTestChat ? "Тестовый чат" : pageTitle}
          </h1>
          <p className="mt-1 text-sm text-[var(--canvas-muted)]">
            {isTestChat
              ? `Песочница с трассировкой для ${profile.name}.`
              : TAB_DESCRIPTIONS[activeTabMeta.id]}
          </p>
        </div>
        {!isTestChat && (
          <OmnichannelStatusStrip statuses={channelMap} size="md" />
        )}
      </div>

      {/* Top agent navigation (MoonAI-style) — not in the left sidebar */}
      <div className="sticky top-0 z-20 -mx-4 border-b border-[var(--canvas-border)] bg-[var(--canvas)]/95 px-4 backdrop-blur-md lg:-mx-8 lg:px-8">
        <div className="overflow-x-auto">
          <div className="flex min-w-max items-center gap-0.5">
            {visibleTabs.map((tab) => {
              const href = getAgentTabPath(botId, tab.id);
              const isActive = !isTestChat && activeTab === tab.id;
              const Icon = TAB_ICONS[tab.id];
              return (
                <Link
                  key={tab.id}
                  href={href}
                  className={cn(
                    "group relative inline-flex items-center gap-2 px-3 py-3 text-sm font-medium transition",
                    isActive
                      ? "text-violet-500 dark:text-violet-300"
                      : "text-[var(--canvas-muted)] hover:text-[var(--canvas-fg)]",
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      isActive ? "text-violet-500" : "opacity-60 group-hover:opacity-100",
                    )}
                  />
                  {tab.label}
                  {isActive && (
                    <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-violet-500" />
                  )}
                </Link>
              );
            })}
            {showTestChat && (
              <Link
                href={getAgentTestChatPath(botId)}
                className={cn(
                  "group relative inline-flex items-center gap-2 px-3 py-3 text-sm font-medium transition",
                  isTestChat
                    ? "text-violet-500 dark:text-violet-300"
                    : "text-[var(--canvas-muted)] hover:text-[var(--canvas-fg)]",
                )}
              >
                <MessageSquare className="h-4 w-4 shrink-0 opacity-70" />
                Тестовый чат
                {isTestChat && (
                  <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-violet-500" />
                )}
              </Link>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
