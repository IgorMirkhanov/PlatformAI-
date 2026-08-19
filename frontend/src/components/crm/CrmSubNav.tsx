"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const CRM_TABS = [
  {
    href: "/dashboard/crm",
    label: "Сделки",
    match: (path: string) => path === "/dashboard/crm" || /^\/dashboard\/crm\/[^/]+$/.test(path),
  },
  {
    href: "/dashboard/crm/contacts",
    label: "Контакты",
    match: (path: string) => path.startsWith("/dashboard/crm/contacts"),
  },
  {
    href: "/dashboard/crm/analytics",
    label: "Аналитика",
    match: (path: string) => path.startsWith("/dashboard/crm/analytics"),
  },
  {
    href: "/dashboard/crm/settings/fields",
    label: "Поля",
    match: (path: string) => path.startsWith("/dashboard/crm/settings/fields"),
  },
  {
    href: "/dashboard/crm/settings/automations",
    label: "Автоматизации",
    match: (path: string) => path.startsWith("/dashboard/crm/settings/automations"),
  },
  {
    href: "/dashboard/crm/settings/webhooks",
    label: "Вебхуки",
    match: (path: string) => path.startsWith("/dashboard/crm/settings/webhooks"),
  },
] as const;

export function CrmSubNav() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-wrap gap-2" aria-label="CRM разделы">
      {CRM_TABS.map((tab) => {
        const active = tab.match(pathname);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm font-medium transition",
              active
                ? "border-violet-500/60 bg-violet-500/15 text-violet-100"
                : "border-zinc-700 bg-zinc-900/50 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
