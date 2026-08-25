"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CreditCard, KeyRound, Users } from "lucide-react";

import { canManageBilling, canManageSettings, canManageTeam } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import type { UserRole } from "@/types/team";

const TABS: Array<{
  href: string;
  label: string;
  icon: typeof Users;
  visible: (role: UserRole | null | undefined) => boolean;
}> = [
  {
    href: "/dashboard/settings/team",
    label: "Команда",
    icon: Users,
    visible: (role) => canManageSettings(role) || canManageTeam(role) || Boolean(role),
  },
  {
    href: "/dashboard/settings/billing",
    label: "Биллинг",
    icon: CreditCard,
    visible: (role) => canManageBilling(role) || canManageSettings(role),
  },
  {
    href: "/dashboard/settings/api-keys",
    label: "API Keys",
    icon: KeyRound,
    visible: (role) => canManageSettings(role),
  },
  {
    href: "/dashboard/byok-vault",
    label: "BYOK Vault",
    icon: KeyRound,
    visible: (role) => canManageSettings(role),
  },
];

export function SettingsSectionNav({ role }: { role: UserRole | null | undefined }) {
  const pathname = usePathname();
  const visible = TABS.filter((tab) => tab.visible(role));
  if (visible.length === 0) {
    return null;
  }

  return (
    <nav className="flex flex-wrap gap-2 border-b border-zinc-800/80 pb-4">
      {visible.map((tab) => {
        const Icon = tab.icon;
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition",
              active
                ? "border-violet-500/40 bg-violet-500/10 text-violet-200"
                : "border-zinc-800 bg-zinc-950/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-100",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
