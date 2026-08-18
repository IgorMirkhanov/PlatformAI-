"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Plus, RefreshCw } from "lucide-react";

import { AgentCardGrid } from "@/components/dashboard/AgentCardGrid";
import { CreateAgentModal } from "@/components/dashboard/CreateAgentModal";
import { DashboardHeroHeader } from "@/components/dashboard/DashboardHeroHeader";
import { ErrorVaultWidget } from "@/components/dashboard/ErrorVaultWidget";
import { MessagesChart } from "@/components/dashboard/MessagesChart";
import { TopUpOverlay } from "@/components/dashboard/TopUpOverlay";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { formatBillingCurrency } from "@/lib/billing-utils";
import {
  fetchDashboardStats,
  fetchDiagnosticLogs,
  triggerDashboardExport,
} from "@/lib/api";
import { buildDailyChartSeries } from "@/lib/dashboard-utils";
import { canManageBots } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import { DEFAULT_BILLING_CURRENCY } from "@/types/billing";
import type { DashboardStatsResponse, DiagnosticLogRead } from "@/types/dashboard";
import { UsageMetersPanel } from "@/components/billing/UsageMetersPanel";

function defaultStartDate(): string {
  const date = new Date();
  date.setDate(date.getDate() - 6);
  return date.toISOString().slice(0, 10);
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function DashboardPage() {
  const { showToast } = useToast();
  const currentUser = useBotStore((state) => state.currentUser);
  const billing = useBotStore((state) => state.billing);
  const loadBilling = useBotStore((state) => state.loadBilling);
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const topUp = useBotStore((state) => state.topUp);
  const canCreateAgents = canManageBots(currentUser?.role);

  const [stats, setStats] = useState<DashboardStatsResponse | null>(null);
  const [diagnosticLogs, setDiagnosticLogs] = useState<DiagnosticLogRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [topUpOpen, setTopUpOpen] = useState(false);
  const [exportStartDate] = useState(defaultStartDate);
  const [exportEndDate] = useState(todayIsoDate);

  const loadStats = useCallback(async (): Promise<void> => {
    setRefreshing(true);
    setLoadError(null);
    try {
      const response = await fetchDashboardStats();
      setStats(response);
    } catch (error) {
      setLoadError(getApiErrorMessage(error, "Не удалось загрузить статистику рабочей области."));
      setStats(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadDiagnostics = useCallback(async (): Promise<void> => {
    setDiagnosticsLoading(true);
    try {
      const response = await fetchDiagnosticLogs(undefined, 20);
      setDiagnosticLogs(response.logs);
    } catch {
      setDiagnosticLogs([]);
    } finally {
      setDiagnosticsLoading(false);
    }
  }, []);

  const refreshAll = useCallback(async (): Promise<void> => {
    await Promise.all([loadStats(), loadDiagnostics(), loadBilling(), loadCurrentUser()]);
  }, [loadBilling, loadCurrentUser, loadDiagnostics, loadStats]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const chartData = useMemo(
    () => (stats ? buildDailyChartSeries(stats) : []),
    [stats],
  );

  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const balance = billing?.balance ?? stats?.subscription_balance ?? 0;
  const plan = billing?.plan_name ?? stats?.subscription_plan ?? "FREE";
  const daysRemaining = billing?.days_remaining ?? null;
  const agentsUsed = stats?.agents.length ?? 0;
  const agentsLimit = billing?.active_agents_limit ?? Math.max(agentsUsed, 1);
  const companyName = currentUser?.company_name ?? "Рабочая группа MP.AI";
  const workspaceId = currentUser?.company_id ?? currentUser?.id ?? "workspace";

  const handleExport = (): void => {
    triggerDashboardExport({
      startDate: exportStartDate,
      endDate: exportEndDate,
    });
    showToast("CSV-отчёт формируется и будет загружен.", "success");
  };

  const handleTopUp = async (amount: number): Promise<void> => {
    try {
      await topUp(amount);
      await loadBilling();
      await loadStats();
      showToast(`Баланс пополнен на ${formatBillingCurrency(amount, currency)}.`, "success");
      setTopUpOpen(false);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Пополнение не удалось."), "error");
      throw error;
    }
  };

  if (loading && !stats && !loadError) {
    return <PageSkeleton />;
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8 p-6 lg:p-8">
      <DashboardHeroHeader
        companyName={companyName}
        workspaceId={workspaceId}
        balance={balance}
        currency={currency}
        plan={plan}
        daysRemaining={daysRemaining}
        agentsUsed={agentsUsed}
        agentsLimit={agentsLimit}
        onTopUpClick={() => setTopUpOpen(true)}
      />

      <UsageMetersPanel organizationId={currentUser?.company_id} />

      {loadError ? (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div className="flex-1">
            <p className="text-sm font-medium text-amber-200">{loadError}</p>
            <button
              type="button"
              onClick={() => void refreshAll()}
              className="mt-2 text-xs font-medium text-amber-300 underline-offset-2 hover:underline"
            >
              Повторить загрузку
            </button>
          </div>
        </div>
      ) : null}

      <section>
        <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-zinc-50">Ваши ИИ-Агенты</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Управление omnichannel-агентами, каналами и статусом в реальном времени.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void refreshAll()}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-[#121214] px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-800/50 disabled:opacity-50"
            >
              <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
              Обновить
            </button>
            {canCreateAgents ? (
              <button
                type="button"
                onClick={() => setCreateModalOpen(true)}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500"
              >
                <Plus className="h-4 w-4" />
                Создать ИИ-Агента
              </button>
            ) : null}
          </div>
        </div>

        {stats ? (
          <AgentCardGrid agents={stats.agents} onRefresh={() => void loadStats()} />
        ) : (
          <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-14 text-center text-sm text-zinc-500">
            Данные агентов недоступны. Проверьте backend и обновите страницу.
          </div>
        )}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        {stats ? (
          <MessagesChart data={chartData} onExport={handleExport} />
        ) : (
          <div className="luxury-card flex min-h-[22rem] items-center justify-center text-sm text-zinc-500">
            График недоступен без статистики API.
          </div>
        )}
        <ErrorVaultWidget logs={diagnosticLogs} loading={diagnosticsLoading} />
      </section>

      {canCreateAgents ? (
        <CreateAgentModal
          open={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onCreated={() => void refreshAll()}
        />
      ) : null}

      <TopUpOverlay
        open={topUpOpen}
        currency={currency}
        onClose={() => setTopUpOpen(false)}
        onTopUp={handleTopUp}
      />
    </div>
  );
}
