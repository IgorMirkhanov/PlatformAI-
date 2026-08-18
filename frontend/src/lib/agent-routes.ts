import type { AgentTabId } from "@/types/agent";

export const AGENT_TABS: Array<{ id: AgentTabId; label: string; segment: string }> = [
  { id: "settings", label: "Настройки", segment: "settings" },
  { id: "prompting", label: "Промптинг", segment: "prompting" },
  { id: "messages", label: "Сообщения", segment: "messages" },
  { id: "llm-models", label: "LLM-Модели", segment: "llm-config" },
  { id: "functions", label: "Функции", segment: "functions" },
  { id: "knowledge-base", label: "База знаний", segment: "knowledge-base" },
  { id: "integrations", label: "Интеграции", segment: "integrations" },
  { id: "channels", label: "Каналы", segment: "channels" },
];

export function getAgentTabPath(botId: string, tab: AgentTabId): string {
  if (tab === "channels") {
    return `/dashboard/channels-agent/${botId}/telegram`;
  }
  const segment = AGENT_TABS.find((item) => item.id === tab)?.segment ?? "settings";
  return `/bots/${botId}/${segment}`;
}

export function getActiveAgentTabFromPath(pathname: string): AgentTabId | null {
  if (/\/dashboard\/channels-agent\/[^/]+/.test(pathname)) {
    return "channels";
  }
  const match = pathname.match(/\/bots\/[^/]+\/([^/?#]+)/);
  if (!match) return null;
  const segment = match[1];
  return AGENT_TABS.find((tab) => tab.segment === segment)?.id ?? null;
}

export function getAgentIdFromPath(pathname: string): string | null {
  const hubMatch = pathname.match(/\/dashboard\/channels-agent\/([^/]+)/);
  if (hubMatch) return hubMatch[1];
  const match = pathname.match(/\/bots\/([^/]+)/);
  return match?.[1] ?? null;
}

export function isAgentWorkspacePath(pathname: string): boolean {
  if (/\/dashboard\/channels-agent\/[^/]+/.test(pathname)) {
    return true;
  }
  return /^\/bots\/[^/]+(\/.*)?$/.test(pathname);
}

export function getAgentTestChatPath(botId: string): string {
  return `/bots/${botId}/test-chat`;
}

export function isAgentTestChatPath(pathname: string): boolean {
  return /\/bots\/[^/]+\/test-chat/.test(pathname);
}
