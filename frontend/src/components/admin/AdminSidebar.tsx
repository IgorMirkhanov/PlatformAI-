"use client";

import Link from "next/link";
import { Suspense } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Activity,
  Bot,
  FileText,
  LogOut,
  Shield,
  Users,
} from "lucide-react";

import { ADMIN_TABS, type AdminTabId } from "@/components/admin/AdminTabNav";
import { cn } from "@/lib/utils";

const EXTRA_NAV = [
  { href: "/admin/users", label: "Пользователи", icon: Users },
  { href: "/admin/health", label: "System Health", icon: Activity },
  { href: "/admin/bots", label: "Bots", icon: Bot },
  { href: "/admin/logs", label: "System Logs", icon: FileText },
] as const;

export function AdminSidebar() {
  return (
    <Suspense fallback={<aside className="w-60 shrink-0 border-r border-zinc-800/80 bg-[#070708]" />}>
      <AdminSidebarInner />
    </Suspense>
  );
}

function AdminSidebarInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeTab = (searchParams.get("tab") as AdminTabId) || "support";

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-zinc-800/80 bg-[#070708]">
      <div className="flex items-center gap-3 border-b border-zinc-800/80 px-4 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/10 ring-1 ring-amber-500/30">
          <Shield className="h-4 w-4 text-amber-300" />
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
            MP.AI
          </p>
          <p className="text-sm font-semibold text-zinc-50">Admin Panel</p>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
        <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
          Разделы
        </p>
        {ADMIN_TABS.map((tab) => {
          const href = `/admin?tab=${tab.id}`;
          const active = pathname === "/admin" && activeTab === tab.id;
          return (
            <Link
              key={tab.id}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition",
                active
                  ? "bg-zinc-100 text-zinc-950"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100",
              )}
            >
              <span className="text-base leading-none">{tab.emoji}</span>
              <span className="truncate">{tab.label}</span>
            </Link>
          );
        })}

        <p className="mt-4 px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
          Инструменты
        </p>
        {EXTRA_NAV.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition",
                active
                  ? "bg-zinc-100 text-zinc-950"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-zinc-800/80 p-3">
        <Link
          href="/dashboard"
          className="flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100"
        >
          <LogOut className="h-4 w-4" />
          В кабинет
        </Link>
      </div>
    </aside>
  );
}
