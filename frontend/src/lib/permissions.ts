import type { AgentTabId } from "@/types/agent";
import type { UserRole } from "@/types/team";

export type Permission =
  | "billing:read"
  | "billing:write"
  | "team:manage"
  | "bot:prompting"
  | "bot:channels"
  | "bot:settings"
  | "bot:knowledge"
  | "bot:llm"
  | "bot:functions"
  | "bot:integrations"
  | "bot:messages"
  | "inbox:read"
  | "dashboard:read"
  | "flow:write"
  | "manage:billing"
  | "manage:flows"
  | "manage:crm"
  | "manage:settings";

const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  OWNER: [
    "billing:read",
    "billing:write",
    "team:manage",
    "bot:prompting",
    "bot:channels",
    "bot:settings",
    "bot:knowledge",
    "bot:llm",
    "bot:functions",
    "bot:integrations",
    "bot:messages",
    "inbox:read",
    "dashboard:read",
    "flow:write",
    "manage:billing",
    "manage:flows",
    "manage:crm",
    "manage:settings",
  ],
  ADMIN: [
    "billing:read",
    "billing:write",
    "team:manage",
    "bot:prompting",
    "bot:channels",
    "bot:settings",
    "bot:knowledge",
    "bot:llm",
    "bot:functions",
    "bot:integrations",
    "bot:messages",
    "inbox:read",
    "dashboard:read",
    "flow:write",
    "manage:billing",
    "manage:flows",
    "manage:crm",
    "manage:settings",
  ],
  MEMBER: [
    "bot:prompting",
    "bot:knowledge",
    "bot:llm",
    "bot:functions",
    "bot:messages",
    "inbox:read",
    "dashboard:read",
    "flow:write",
    "manage:flows",
  ],
  PROMPT_ENGINEER: [
    "bot:prompting",
    "bot:knowledge",
    "bot:llm",
    "bot:functions",
    "bot:messages",
    "bot:settings",
    "inbox:read",
    "dashboard:read",
    "flow:write",
    "manage:flows",
  ],
  OPERATOR: ["inbox:read", "dashboard:read", "manage:crm"],
};

const AGENT_TAB_PERMISSIONS: Record<AgentTabId, Permission> = {
  settings: "bot:settings",
  prompting: "bot:prompting",
  messages: "bot:messages",
  "llm-models": "bot:llm",
  functions: "bot:functions",
  "knowledge-base": "bot:knowledge",
  integrations: "bot:integrations",
  channels: "bot:channels",
};

export function hasPermission(role: UserRole | null | undefined, permission: Permission): boolean {
  if (!role) {
    return false;
  }
  return ROLE_PERMISSIONS[role]?.includes(permission) ?? false;
}

export function canAccessAgentTab(role: UserRole | null | undefined, tab: AgentTabId): boolean {
  return hasPermission(role, AGENT_TAB_PERMISSIONS[tab]);
}

export function canManageTeam(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "team:manage");
}

export function canManageBots(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "bot:settings");
}

export function canAccessBilling(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "billing:read");
}

export function canManageBilling(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "manage:billing");
}

export function canManageFlows(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "manage:flows");
}

export function canManageCrm(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "manage:crm");
}

export function canManageSettings(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "manage:settings");
}

export function canAccessFlowBuilder(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "flow:write");
}

export function canAccessSandbox(role: UserRole | null | undefined): boolean {
  return hasPermission(role, "bot:messages");
}
