"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { cn } from "@/lib/utils";

export const ADMIN_TABS = [
  { id: "support", label: "Поиск и Поддержка клиентов", emoji: "🔍" },
  { id: "llm", label: "LLM Модели и Цены", emoji: "🤖" },
  { id: "billing", label: "Организации и Биллинг", emoji: "💳" },
  { id: "audit", label: "Логи аудита", emoji: "📜" },
] as const;

export type AdminTabId = (typeof ADMIN_TABS)[number]["id"];

export function AdminTabNav() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const active = (searchParams.get("tab") as AdminTabId) || "support";

  const setTab = useCallback(
    (tab: AdminTabId) => {
      const next = new URLSearchParams(searchParams.toString());
      next.set("tab", tab);
      router.replace(`/admin?${next.toString()}`);
    },
    [router, searchParams],
  );

  return (
    <nav className="flex flex-wrap gap-2 border-b border-zinc-800/80 pb-4">
      {ADMIN_TABS.map((tab) => {
        const isActive = active === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => setTab(tab.id)}
            className={cn(
              "rounded-xl px-3 py-2 text-sm font-medium transition",
              isActive
                ? "bg-amber-500/15 text-amber-100 ring-1 ring-amber-500/40"
                : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100",
            )}
          >
            <span className="mr-1.5">{tab.emoji}</span>
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

export function useAdminTab(): AdminTabId {
  const searchParams = useSearchParams();
  const raw = searchParams.get("tab");
  if (raw === "llm" || raw === "billing" || raw === "audit") return raw;
  return "support";
}
