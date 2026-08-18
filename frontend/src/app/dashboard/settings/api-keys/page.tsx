"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { ApiKeySettings } from "@/components/settings/ApiKeySettings";
import { SettingsSectionNav } from "@/components/settings/SettingsSectionNav";
import { canManageSettings } from "@/lib/permissions";
import { useBotStore } from "@/store/useBotStore";

export default function DashboardApiKeySettingsPage() {
  const currentUser = useBotStore((s) => s.currentUser);
  const loadCurrentUser = useBotStore((s) => s.loadCurrentUser);
  const allowed = canManageSettings(currentUser?.role);

  useEffect(() => {
    if (!currentUser) {
      void loadCurrentUser();
    }
  }, [currentUser, loadCurrentUser]);

  if (!allowed) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 text-sm text-zinc-400">
        Недостаточно прав для управления API-ключами организации.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-2 text-xs text-zinc-500 hover:text-zinc-300"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Назад в dashboard
      </Link>

      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
          Organization Settings
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-zinc-50">API Keys</h1>
      </div>

      <SettingsSectionNav role={currentUser?.role} />
      <ApiKeySettings />
    </div>
  );
}
