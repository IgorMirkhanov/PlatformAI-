"use client";

import { Suspense, useEffect, useState } from "react";
import { Bot, Coins, Loader2, ScrollText } from "lucide-react";

import { StatCard } from "@/components/admin/StatCard";
import { AdminTabNav, useAdminTab } from "@/components/admin/AdminTabNav";
import { AdminAuditTab } from "@/components/admin/tabs/AdminAuditTab";
import { AdminBillingTab } from "@/components/admin/tabs/AdminBillingTab";
import { AdminLlmModelsTab } from "@/components/admin/tabs/AdminLlmModelsTab";
import { AdminSupportTab } from "@/components/admin/tabs/AdminSupportTab";
import { fetchAdminStats } from "@/lib/api";
import type { AdminStatsResponse } from "@/types/admin";

function AdminStatsStrip() {
  const [stats, setStats] = useState<AdminStatsResponse | null>(null);

  useEffect(() => {
    void fetchAdminStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  const tokens = stats?.total_tokens ?? 0;
  const errors = stats?.error_log_count ?? 0;

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard
        title="Активные боты"
        value={stats ? String(stats.total_active_bots) : "—"}
        hint="Боты со статусом active"
        icon={Bot}
      />
      <StatCard
        title="Потраченные токены"
        value={stats ? tokens.toLocaleString("ru-RU") : "—"}
        hint="Сумма prompt + completion"
        icon={Coins}
      />
      <StatCard
        title="Логи ошибок"
        value={stats ? String(errors) : "—"}
        hint="Записи в diagnostic vault"
        icon={ScrollText}
      />
    </div>
  );
}

function AdminHomeContent() {
  const tab = useAdminTab();

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Админ-панель</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Пользователи и балансы, роли, статистика системы, модели LLM и журнал аудита.
        </p>
      </header>

      <AdminStatsStrip />

      <AdminTabNav />

      {tab === "support" ? <AdminSupportTab /> : null}
      {tab === "llm" ? <AdminLlmModelsTab /> : null}
      {tab === "billing" ? <AdminBillingTab /> : null}
      {tab === "audit" ? <AdminAuditTab /> : null}
    </div>
  );
}

export default function AdminHomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка…
        </div>
      }
    >
      <AdminHomeContent />
    </Suspense>
  );
}
