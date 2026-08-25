"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Bot,
  Briefcase,
  CreditCard,
  LayoutDashboard,
  LayoutTemplate,
  Menu,
  MessageCircle,
  Settings,
  Sparkles,
  TestTube2,
  Wallet,
  KeyRound,
  Workflow,
  X,
  Zap,
} from "lucide-react";

import { CreateAgentButton } from "@/components/layout/CreateAgentButton";
import { HeaderNotificationBell } from "@/components/layout/HeaderNotificationBell";
import { HeaderWalletWidget } from "@/components/layout/HeaderWalletWidget";
import { UserHeaderDropdown } from "@/components/layout/UserHeaderDropdown";
import { ImpersonationBanner } from "@/components/ImpersonationBanner";
import { OmnichannelStatusStrip } from "@/components/channels/OmnichannelStatusStrip";
import { OrgSwitcher } from "@/components/dashboard/OrgSwitcher";
import { LowBalanceBanner } from "@/components/dashboard/LowBalanceBanner";
import { WorkspaceQuotaWidget } from "@/components/dashboard/WorkspaceQuotaWidget";
import { fetchDashboardStats } from "@/lib/api";
import {
  AGENT_TABS,
  getAgentIdFromPath,
  getAgentTabPath,
  getAgentTestChatPath,
  isAgentTestChatPath,
  isAgentWorkspacePath,
} from "@/lib/agent-routes";
import {
  canAccessAgentTab,
  canAccessBilling,
  canAccessFlowBuilder,
  canAccessSandbox,
  canManageBilling,
  canManageSettings,
  canManageTeam,
  hasPermission,
} from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { mergeChannelStatuses } from "@/types/channels";
import type { AgentTabId } from "@/types/agent";
import type { AgentStatusSummary } from "@/types/dashboard";

const WORKSPACE_NAV = [
  {
    href: "/dashboard",
    label: "Дашборд",
    icon: LayoutDashboard,
    isActive: (pathname: string) => pathname === "/dashboard",
  },
  {
    href: "/dashboard/crm",
    label: "CRM",
    icon: Briefcase,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/crm"),
  },
  {
    href: "/dashboard/wallet",
    label: "Кошелёк",
    icon: Wallet,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/wallet"),
  },
  {
    href: "/dashboard/byok-vault",
    label: "BYOK",
    icon: KeyRound,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/byok-vault"),
  },
  {
    href: "/dashboard/playground",
    label: "Playground",
    icon: TestTube2,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/playground"),
  },
  {
    href: "/dashboard/knowledge",
    label: "База знаний",
    icon: BookOpen,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/knowledge"),
  },
  {
    href: "/dashboard/flows",
    label: "Flows",
    icon: Workflow,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/flows"),
  },
  {
    href: "/dashboard/templates",
    label: "Шаблоны",
    icon: LayoutTemplate,
    isActive: (pathname: string) => pathname.startsWith("/dashboard/templates"),
  },
  {
    href: "/flow-builder",
    label: "Конструктор",
    icon: Zap,
    isActive: (pathname: string) => pathname.startsWith("/flow-builder"),
  },
  {
    href: "/inbox",
    label: "Диалоги",
    icon: MessageCircle,
    isActive: (pathname: string) => pathname.startsWith("/inbox"),
  },
] as const;

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const loadBilling = useBotStore((state) => state.loadBilling);
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const currentUser = useBotStore((state) => state.currentUser);
  const activeBotId = useBotStore((state) => state.activeBotId);
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const agentProfiles = useBotStore((state) => state.agentProfiles);
  const channelStatuses = useBotStore((state) => state.channelStatuses);
  const loadBotChannels = useBotStore((state) => state.loadBotChannels);

  const userRole = currentUser?.role;
  const showBilling = canAccessBilling(userRole);
  const showSettingsBilling = canManageBilling(userRole) || canManageSettings(userRole);
  const showTeamSettings = canManageTeam(userRole) || canManageSettings(userRole) || Boolean(currentUser);
  const showSettingsNav = showTeamSettings || showSettingsBilling;
  const visibleWorkspaceNav = WORKSPACE_NAV.filter((item) => {
    if (item.href === "/dashboard") {
      return hasPermission(userRole, "dashboard:read");
    }
    if (item.href === "/dashboard/crm") {
      // Native CRM API is OWNER/ADMIN — mirror that on the nav.
      return userRole === "OWNER" || userRole === "ADMIN";
    }
    if (item.href === "/dashboard/knowledge") {
      return hasPermission(userRole, "bot:knowledge");
    }
    if (item.href === "/flow-builder" || item.href === "/dashboard/flows" || item.href === "/dashboard/templates") {
      return canAccessFlowBuilder(userRole);
    }
    if (item.href === "/dashboard/wallet") {
      return canAccessBilling(userRole);
    }
    if (item.href === "/dashboard/byok-vault") {
      return canManageSettings(userRole);
    }
    if (item.href === "/dashboard/playground") {
      return canAccessSandbox(userRole);
    }
    if (item.href === "/inbox") {
      return hasPermission(userRole, "inbox:read");
    }
    return true;
  });
  const visibleAgentTabs = AGENT_TABS.filter((tab) => canAccessAgentTab(userRole, tab.id));
  const canOpenAgentWorkspace = visibleAgentTabs.length > 0;
  const showTestChat = canAccessSandbox(userRole);

  const [agents, setAgents] = useState<AgentStatusSummary[]>([]);

  const routeBotId = getAgentIdFromPath(pathname);
  const workspaceBotId = routeBotId ?? activeBotId;
  const inAgentWorkspace = Boolean(
    isAgentWorkspacePath(pathname) && workspaceBotId && canOpenAgentWorkspace,
  );
  const testChatActive = isAgentTestChatPath(pathname);
  const activeProfile = workspaceBotId ? agentProfiles[workspaceBotId] : undefined;

  const agentList = useMemo(() => {
    if ((agents ?? []).length > 0) {
      return agents;
    }
    return Object.values(agentProfiles).map((profile) => ({
      bot_id: profile.id,
      bot_name: profile.name,
      platform_type: profile.platform_type,
      is_active: profile.is_active,
      channel_connected: false,
      flow_published: false,
      unique_dialogs: 0,
    }));
  }, [agents, agentProfiles]);

  const loadAgents = useCallback(async (): Promise<void> => {
    try {
      const stats = await fetchDashboardStats();
      setAgents(Array.isArray(stats.agents) ? stats.agents : []);
    } catch {
      setAgents([]);
    }
  }, []);

  useEffect(() => {
    void loadCurrentUser();
    if (showBilling) {
      void loadBilling();
    }
    void loadAgents();
  }, [loadAgents, loadBilling, loadCurrentUser, showBilling]);

  useEffect(() => {
    if (workspaceBotId && inAgentWorkspace) {
      void loadBotChannels(workspaceBotId);
    }
  }, [inAgentWorkspace, loadBotChannels, workspaceBotId]);

  const openAgent = (botId: string, tab: AgentTabId = "settings"): void => {
    if (!canAccessAgentTab(userRole, tab)) {
      router.push("/inbox");
      onNavigate?.();
      return;
    }
    setActiveBotId(botId);
    router.push(getAgentTabPath(botId, tab));
    onNavigate?.();
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto pr-1">
        <div className="mb-5 flex items-center gap-3 px-1">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 shadow-glow-purple">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div>
            <p className="text-base font-bold tracking-tight text-white">MP.AI</p>
            <p className="text-[11px] text-zinc-500">Production Console</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {showBilling && (
            <Link
              href="/dashboard/billing"
              onClick={onNavigate}
              className={cn(
                "inline-flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition",
                pathname.startsWith("/dashboard/billing") || pathname.startsWith("/billing")
                  ? "border-violet-500/40 bg-violet-500/10 text-violet-200"
                  : "border-zinc-800 bg-zinc-950/60 text-zinc-300 hover:border-zinc-700 hover:text-white",
              )}
            >
              <CreditCard className="h-3.5 w-3.5" />
              Подписки
            </Link>
          )}
          <Link
            href="/dashboard"
            onClick={onNavigate}
            className={cn(
              "inline-flex items-center justify-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:border-zinc-700 hover:text-white",
              !showBilling && "col-span-2",
            )}
          >
            <Sparkles className="h-3.5 w-3.5 text-violet-400" />
            Первый запуск
          </Link>
        </div>

        {showSettingsNav && (
          <div className="mt-3 space-y-2">
            <p className="px-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
              Настройки
            </p>
            {showTeamSettings && (
              <Link
                href="/dashboard/settings/team"
                onClick={onNavigate}
                className={cn(
                  "inline-flex w-full items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition",
                  pathname.startsWith("/dashboard/settings/team") ||
                    pathname.startsWith("/settings/team")
                    ? "border-violet-500/40 bg-violet-500/10 text-violet-200"
                    : "border-zinc-800 bg-zinc-950/60 text-zinc-300 hover:border-zinc-700 hover:text-white",
                )}
              >
                <Settings className="h-3.5 w-3.5" />
                Команда
              </Link>
            )}
            {showSettingsBilling && (
              <Link
                href="/dashboard/settings/billing"
                onClick={onNavigate}
                className={cn(
                  "inline-flex w-full items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition",
                  pathname.startsWith("/dashboard/settings/billing")
                    ? "border-violet-500/40 bg-violet-500/10 text-violet-200"
                    : "border-zinc-800 bg-zinc-950/60 text-zinc-300 hover:border-zinc-700 hover:text-white",
                )}
              >
                <CreditCard className="h-3.5 w-3.5" />
                Биллинг
              </Link>
            )}
          </div>
        )}

        {inAgentWorkspace && workspaceBotId ? (
          <>
            <Link
              href="/dashboard"
              onClick={onNavigate}
              className="mt-5 inline-flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-zinc-500 transition hover:bg-zinc-900/70 hover:text-zinc-200"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Рабочее пространство
            </Link>

            {activeProfile && (
              <div className="moonai-agent-chip mt-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-violet-300/80">
                  Активный агент
                </p>
                <p className="mt-1 truncate text-sm font-semibold text-zinc-100">
                  {activeProfile.name}
                </p>
                <p className="text-[10px] text-zinc-500">{activeProfile.platform_type}</p>
                <div className="mt-3">
                  <OmnichannelStatusStrip
                    statuses={
                      channelStatuses[workspaceBotId] ?? mergeChannelStatuses([])
                    }
                    size="sm"
                  />
                </div>
              </div>
            )}

            <nav className="mt-5 space-y-0.5">
              <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                Рабочее пространство
              </p>
              {visibleWorkspaceNav.map((item) => {
                const isActive = item.isActive(pathname);
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onNavigate}
                    className={cn(
                      "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                      isActive
                        ? "bg-violet-500/12 text-violet-100 shadow-glow-purple ring-1 ring-violet-500/25"
                        : "text-zinc-400 hover:bg-zinc-900/70 hover:text-zinc-100",
                    )}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        isActive ? "text-violet-300" : "text-zinc-500 group-hover:text-zinc-300",
                      )}
                    />
                    {item.label}
                  </Link>
                );
              })}
              {showTestChat && (
                <Link
                  href={getAgentTestChatPath(workspaceBotId)}
                  onClick={onNavigate}
                  className={cn(
                    "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                    testChatActive
                      ? "bg-violet-500/12 text-violet-100 shadow-glow-purple ring-1 ring-violet-500/25"
                      : "text-zinc-400 hover:bg-zinc-900/70 hover:text-zinc-100",
                  )}
                >
                  <TestTube2
                    className={cn(
                      "h-4 w-4 shrink-0",
                      testChatActive ? "text-violet-300" : "text-zinc-500 group-hover:text-zinc-300",
                    )}
                  />
                  Тестовый чат
                </Link>
              )}
            </nav>
          </>
        ) : (
          <nav className="mt-6 space-y-0.5">
            <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
              Рабочее пространство
            </p>
            {visibleWorkspaceNav.map((item) => {
              const isActive = item.isActive(pathname);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  className={cn(
                    "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                    isActive
                      ? "bg-violet-500/12 text-violet-100 shadow-glow-purple ring-1 ring-violet-500/25"
                      : "text-zinc-400 hover:bg-zinc-900/70 hover:text-zinc-100",
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      isActive ? "text-violet-300" : "text-zinc-500 group-hover:text-zinc-300",
                    )}
                  />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        )}

        {canOpenAgentWorkspace && (
          <div className="mt-6">
          <div className="mb-2 flex items-center justify-between px-2">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
              ИИ Агенты
            </p>
            <CreateAgentButton variant="icon" onNavigate={onNavigate} onCreated={loadAgents} />
          </div>

          {agentList.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-800 px-3 py-4 text-center">
              <p className="text-xs text-zinc-500">Агенты не найдены</p>
              <div className="mt-2">
                <CreateAgentButton variant="link" onNavigate={onNavigate} onCreated={loadAgents} />
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              {agentList.map((agent) => {
                const isSelected = workspaceBotId === agent.bot_id;

                return (
                  <button
                    key={agent.bot_id}
                    type="button"
                    onClick={() => openAgent(agent.bot_id, "settings")}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition",
                      isSelected
                        ? "border-violet-500/30 bg-violet-500/10"
                        : "border-transparent hover:border-zinc-800 hover:bg-zinc-900/50",
                    )}
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-900 ring-1 ring-zinc-800">
                      <Bot className="h-4 w-4 text-violet-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-zinc-100">{agent.bot_name}</p>
                      <p className="truncate text-[10px] text-zinc-500">{agent.platform_type}</p>
                    </div>
                    <span
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        agent.is_active ? "bg-emerald-400" : "bg-zinc-600",
                      )}
                    />
                  </button>
                );
              })}
            </div>
          )}
        </div>
        )}
      </div>

      <div className="mt-4 shrink-0 space-y-3">
        <WorkspaceQuotaWidget />
        <div className="rounded-xl border border-zinc-800/60 bg-zinc-950/50 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">MP.AI Platform</p>
          <p className="mt-1 text-xs text-zinc-500">Единая консоль · KZT billing</p>
          <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-zinc-500">
            <Link href="/dashboard/help" className="hover:text-zinc-300">
              Справка
            </Link>
            <Link href="/support" className="hover:text-zinc-300">
              Поддержка
            </Link>
            <Link href="/privacy" className="hover:text-zinc-300">
              Privacy
            </Link>
            <Link href="/terms" className="hover:text-zinc-300">
              Terms
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const isAdminSurface =
    pathname.startsWith("/admin") || pathname.startsWith("/dashboard/admin");
  const isAdminLogin = pathname === "/admin/login";
  const isLandingSurface = pathname === "/";
  const isAuthSurface =
    isLandingSurface ||
    isAdminLogin ||
    pathname === "/login" ||
    pathname === "/register" ||
    pathname === "/forgot-password" ||
    pathname === "/reset-password" ||
    pathname === "/privacy" ||
    pathname === "/terms" ||
    pathname === "/support" ||
    pathname === "/help" ||
    pathname.startsWith("/legal") ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/register/") ||
    pathname.startsWith("/forgot-password/") ||
    pathname.startsWith("/reset-password/") ||
    pathname.startsWith("/integrations/hub/oauth-result");

  if (isAuthSurface) {
    return (
      <div className={cn("min-h-screen", isLandingSurface ? "bg-[#050507]" : "bg-black")}>
        <main>{children}</main>
      </div>
    );
  }

  if (isAdminSurface && !isAdminLogin) {
    return (
      <div className="flex h-screen min-h-0 flex-col overflow-hidden bg-black">
        <ImpersonationBanner />
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-hidden bg-black">
      <aside className="moonai-sidebar fixed inset-y-0 left-0 z-40 hidden h-screen w-[17.5rem] flex-col border-r border-zinc-800/80 bg-[#070708] p-4 lg:flex">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/80 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-label="Close menu overlay"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-zinc-800/80 bg-[#070708] p-4 transition-transform duration-300 lg:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <button
          type="button"
          onClick={() => setMobileOpen(false)}
          className="absolute right-3 top-3 rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-800/50"
          aria-label="Close menu"
        >
          <X className="h-5 w-5" />
        </button>
        <SidebarContent onNavigate={() => setMobileOpen(false)} />
      </aside>

      <div className="flex h-screen min-h-0 flex-col overflow-hidden bg-black lg:pl-[17.5rem]">
        <ImpersonationBanner />
        <LowBalanceBanner />
        <header className="sticky top-0 z-30 flex shrink-0 items-center justify-between gap-3 border-b border-zinc-800/80 bg-black/90 px-4 py-3 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-800/50 hover:text-white lg:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <span className="text-sm font-bold text-white lg:hidden">MP.AI</span>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="hidden md:block">
              <OrgSwitcher />
            </div>
            <HeaderWalletWidget />
            <HeaderNotificationBell />
            <UserHeaderDropdown />
          </div>
        </header>

        {/* Outer clips to viewport; inner is the single page scroller for tall routes.
            Hub pages use flex-1 + overflow-hidden so only their section scrolls. */}
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-black">
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
        </main>
      </div>
    </div>
  );
}
