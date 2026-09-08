import type { AgentTabId } from "@/types/agent";

export const AGENT_TABS: Array<{ id: AgentTabId; label: string; segment: string }> = [
  { id: "settings", label: "Настройки", segment: "settings" },
  { id: "prompting", label: "Промптинг", segment: "prompting" },
  { id: "messages", label: "Сообщения", segment: "messages" },
  { id: "llm-models", label: "LLM-Модели", segment: "llm-config" },
  { id: "control", label: "Контроль", segment: "control" },
  { id: "functions", label: "Функции", segment: "functions" },
  { id: "knowledge-base", label: "База знаний", segment: "knowledge-base" },
  { id: "integrations", label: "Интеграции", segment: "integrations" },
  { id: "channels", label: "Каналы", segment: "channels" },
  { id: "scenario", label: "Сценарий", segment: "scenario" },
];

export function getAgentTabPath(botId: string, tab: AgentTabId): string {
  if (tab === "channels") {
    return `/dashboard/channels?botId=${encodeURIComponent(botId)}`;
  }
  if (tab === "integrations") {
    return `/dashboard/integrations?botId=${encodeURIComponent(botId)}`;
  }
  if (tab === "functions") {
    return `/bots/${botId}/functions`;
  }
  if (tab === "scenario") {
    return `/flow-builder?botId=${encodeURIComponent(botId)}`;
  }
  const segment = AGENT_TABS.find((item) => item.id === tab)?.segment ?? "settings";
  return `/bots/${botId}/${segment}`;
}

export function getActiveAgentTabFromPath(pathname: string): AgentTabId | null {
  if (/\/dashboard\/channels(\?|$|\/)/.test(pathname)) {
    return "channels";
  }
  if (/\/dashboard\/integrations(\?|$|\/)/.test(pathname)) {
    return "integrations";
  }
  if (/\/dashboard\/functions(\?|$|\/)/.test(pathname)) {
    return "functions";
  }
  if (/\/dashboard\/channels-agent\/[^/]+/.test(pathname)) {
    return "channels";
  }
  if (/^\/flow-builder(\?|$|\/)/.test(pathname) || /^\/dashboard\/flow-builder(\/|$)/.test(pathname)) {
    return "scenario";
  }
  if (/\/dashboard\/flows(\/|$)/.test(pathname)) {
    return null;
  }
  const match = pathname.match(/\/bots\/[^/]+\/([^/?#]+)/);
  if (!match) return null;
  const segment = match[1];
  return AGENT_TABS.find((tab) => tab.segment === segment)?.id ?? null;
}

export function getAgentIdFromPath(pathname: string, searchParams?: URLSearchParams | null): string | null {
  if (searchParams?.get("botId")) {
    return searchParams.get("botId");
  }
  const queryMatch = pathname.match(/[?&]botId=([^&]+)/);
  if (queryMatch?.[1]) {
    return decodeURIComponent(queryMatch[1]);
  }
  const channelsMatch = pathname.match(/\/dashboard\/channels(?:-agent)?\/([^/?#]+)/);
  if (channelsMatch) return channelsMatch[1];
  const flowBuilderMatch = pathname.match(/\/dashboard\/flow-builder\/([^/?#]+)/);
  if (flowBuilderMatch) return flowBuilderMatch[1];
  const match = pathname.match(/\/bots\/([^/]+)/);
  return match?.[1] ?? null;
}

export function isAgentWorkspacePath(pathname: string): boolean {
  if (/\/dashboard\/(channels|integrations|functions)(\/|\?|$)/.test(pathname)) {
    return true;
  }
  if (/\/dashboard\/channels-agent\/[^/]+/.test(pathname)) {
    return true;
  }
  if (/^\/flow-builder(\?|$|\/)/.test(pathname) || /^\/dashboard\/flow-builder(\/|$)/.test(pathname)) {
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
