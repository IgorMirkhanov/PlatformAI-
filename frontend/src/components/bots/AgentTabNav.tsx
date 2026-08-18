"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { AGENT_TABS, getActiveAgentTabFromPath, getAgentTabPath } from "@/lib/agent-routes";
import { cn } from "@/lib/utils";

interface AgentTabNavProps {
  botId: string;
  variant?: "bar" | "sidebar";
}

export function AgentTabNav({ botId, variant = "bar" }: AgentTabNavProps) {
  const pathname = usePathname();
  const activeTab = getActiveAgentTabFromPath(pathname) ?? "settings";

  if (variant === "sidebar") {
    return (
      <div className="mt-4 space-y-1 border-t border-zinc-800 pt-4">
        <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
          Агент
        </p>
        {AGENT_TABS.map((tab) => {
          const href = getAgentTabPath(botId, tab.id);
          const isActive = activeTab === tab.id;

          return (
            <Link
              key={tab.id}
              href={href}
              className={cn(
                "block rounded-lg border border-transparent px-3 py-2 text-xs font-medium transition",
                isActive
                  ? "border-indigo-500/30 bg-zinc-900 text-indigo-300"
                  : "text-zinc-500 hover:border-zinc-800 hover:bg-zinc-800/50 hover:text-zinc-200",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    );
  }

  return (
    <nav className="agent-tab-bar">
      <div className="flex gap-1 overflow-x-auto">
        {AGENT_TABS.map((tab) => {
          const href = getAgentTabPath(botId, tab.id);
          const isActive = activeTab === tab.id;

          return (
            <Link
              key={tab.id}
              href={href}
              className={cn("agent-tab-link", isActive && "agent-tab-link-active")}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
