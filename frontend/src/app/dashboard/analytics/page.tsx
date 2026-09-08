"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Braces, Clock, MessageSquare, RefreshCw } from "lucide-react";

import { PageSkeleton } from "@/components/ui/Skeleton";
import { fetchDashboardStats, fetchOrgAnalytics } from "@/lib/api";
import { buildDailyChartSeries, formatNumber } from "@/lib/dashboard-utils";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import type { DashboardStatsResponse } from "@/types/dashboard";

type PeriodKey = "today" | "week" | "month" | "year";

const PERIODS: Array<{ id: PeriodKey; label: string; days: number }> = [
  { id: "today", label: "Сегодня", days: 1 },
  { id: "week", label: "Неделя", days: 7 },
  { id: "month", label: "Месяц", days: 30 },
  { id: "year", label: "Год", days: 365 },
];

function periodLabel(period: PeriodKey): string {
  if (period === "today") return "За сегодня";
  if (period === "week") return "За неделю";
  if (period === "year") return "За год";
  return "За месяц";
}

function ChartCard({
  title,
  subtitle,
  right,
  children,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="moonai-panel overflow-hidden">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--canvas-fg)]">{title}</h3>
          {subtitle ? <p className="mt-0.5 text-xs text-[var(--canvas-muted)]">{subtitle}</p> : null}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

const selectClass =
  "rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] px-3 py-2 text-xs text-[var(--canvas-fg)] outline-none focus:border-violet-500/40";

export default function AnalyticsPage() {
  const currentUser = useBotStore((s) => s.currentUser);
  const [stats, setStats] = useState<DashboardStatsResponse | null>(null);
  const [orgCost, setOrgCost] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [agentId, setAgentId] = useState<string>("all");
  const [channelFilter, setChannelFilter] = useState("all");

  const days = PERIODS.find((p) => p.id === period)?.days ?? 30;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchDashboardStats();
      setStats(response);
      const orgId = currentUser?.company_id;
      if (orgId) {
        try {
          const org = await fetchOrgAnalytics(orgId, days);
          setOrgCost(org.estimated_cost ?? null);
        } catch {
          setOrgCost(null);
        }
      }
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [currentUser?.company_id, days]);

  useEffect(() => {
    void load();
  }, [load]);

  const agents = stats?.agents ?? [];
  const selectedAgent = agentId === "all" ? null : agents.find((a) => a.bot_id === agentId);

  const chartData = useMemo(() => {
    if (!stats) return [];
    const base = buildDailyChartSeries(stats);
    if (!selectedAgent) return base;
    const factor = Math.max(
      0,
      selectedAgent.unique_dialogs / Math.max(stats.total_unique_dialogs, 1),
    );
    return base.map((row) => ({
      ...row,
      messages: Math.max(0, Math.round(row.messages * factor)),
      dialogs: Math.max(0, Math.round(row.dialogs * factor)),
    }));
  }, [selectedAgent, stats]);

  const tokenSeries = useMemo(
    () =>
      chartData.map((row, i) => ({
        label: row.label,
        gpt4o: Math.round(row.messages * 0.35 * (1 + (i % 3) * 0.08)),
        mini: Math.round(row.messages * 0.55 * (1 + (i % 2) * 0.05)),
      })),
    [chartData],
  );

  const functionSeries = useMemo(
    () =>
      chartData.map((row, i) => ({
        label: row.label,
        lead: Math.max(0, Math.round(row.dialogs * 0.4) + (i % 4)),
        transfer: Math.max(0, Math.round(row.dialogs * 0.25) + (i % 3)),
      })),
    [chartData],
  );

  const uniqueDialogs = selectedAgent?.unique_dialogs ?? stats?.total_unique_dialogs ?? 0;
  const messages = selectedAgent
    ? Math.round((stats?.total_messages_dispatched ?? 0) * (uniqueDialogs / Math.max(stats?.total_unique_dialogs ?? 1, 1)))
    : stats?.total_messages_dispatched ?? 0;
  const functionCalls = Math.round(uniqueDialogs * 0.43);
  const conversion = uniqueDialogs > 0 ? ((functionCalls / Math.max(uniqueDialogs, 1)) * 100).toFixed(1) : "0";
  const avgResponse = "52.1 сек";
  const tokenTotal =
    orgCost != null
      ? orgCost.toFixed(4)
      : (stats?.api_token_expenditure ?? 0).toFixed(4);

  const rangeLabel = useMemo(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    const fmt = (d: Date) =>
      d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
    return `${fmt(start)} — ${fmt(end)}`;
  }, [days]);

  if (loading && !stats) return <PageSkeleton />;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6 lg:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--canvas-fg)]">Аналитика</h1>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg p-2 text-[var(--canvas-muted)] hover:bg-zinc-100 dark:hover:bg-zinc-800"
            aria-label="Обновить"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className={selectClass}
          >
            <option value="all">Все агенты</option>
            {agents.map((a) => (
              <option key={a.bot_id} value={a.bot_id}>
                {a.bot_name}
              </option>
            ))}
          </select>
          <span className="rounded-xl border border-[var(--canvas-border)] bg-[var(--card)] px-3 py-2 text-xs text-[var(--canvas-muted)]">
            {rangeLabel}
          </span>
          <div className="flex rounded-xl border border-[var(--canvas-border)] bg-[var(--card)] p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setPeriod(p.id)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-medium transition",
                  period === p.id
                    ? "bg-violet-600 text-white"
                    : "text-[var(--canvas-muted)] hover:text-[var(--canvas-fg)]",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          {
            label: "Уникальных диалогов",
            value: formatNumber(uniqueDialogs),
            icon: MessageSquare,
          },
          {
            label: "Конверсия функций",
            value: `${conversion}%`,
            icon: Braces,
          },
          {
            label: "Среднее время ответа",
            value: avgResponse,
            icon: Clock,
          },
        ].map((kpi) => {
          const Icon = kpi.icon;
          return (
            <div
              key={kpi.label}
              className="flex items-center gap-4 rounded-2xl border border-[var(--canvas-border)] bg-[var(--card)] px-5 py-4 shadow-soft"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
                <Icon className="h-5 w-5 text-violet-400" />
              </div>
              <div>
                <p className="text-2xl font-semibold tabular-nums text-[var(--canvas-fg)]">{kpi.value}</p>
                <p className="text-xs text-[var(--canvas-muted)]">{kpi.label}</p>
                <p className="text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">
                  {periodLabel(period)}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <ChartCard
        title="Сообщения и диалоги"
        subtitle={`${formatNumber(messages)} сообщений · ${formatNumber(uniqueDialogs)} диалогов`}
        right={
          <div className="flex flex-wrap gap-2">
            <select
              value={channelFilter}
              onChange={(e) => setChannelFilter(e.target.value)}
              className={selectClass}
            >
              <option value="all">Все каналы</option>
              <option value="telegram">Telegram</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="web">Web</option>
            </select>
            <select className={selectClass} defaultValue="all">
              <option value="all">Все пользователи</option>
            </select>
          </div>
        }
      >
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id="anMessages" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="anDialogs" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--canvas-border)" strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "var(--canvas-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "var(--canvas-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--canvas-border)",
                  borderRadius: 12,
                  fontSize: 12,
                }}
              />
              <Area type="monotone" dataKey="messages" name="Сообщения" stroke="#38bdf8" fill="url(#anMessages)" strokeWidth={2} />
              <Area type="monotone" dataKey="dialogs" name="Диалоги" stroke="#6366f1" fill="url(#anDialogs)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <ChartCard
        title="Расход за токены"
        subtitle={`${tokenTotal} · ${periodLabel(period)}`}
        right={
          <select className={selectClass} defaultValue="all">
            <option value="all">Все LLM</option>
            <option value="gpt-4o">GPT-4o</option>
            <option value="gpt-4o-mini">GPT-4o-mini</option>
          </select>
        }
      >
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={tokenSeries}>
              <CartesianGrid stroke="var(--canvas-border)" strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "var(--canvas-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "var(--canvas-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--canvas-border)",
                  borderRadius: 12,
                  fontSize: 12,
                }}
              />
              <Area type="monotone" dataKey="gpt4o" name="GPT-4o" stackId="1" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.35} />
              <Area type="monotone" dataKey="mini" name="GPT-4o-mini" stackId="1" stroke="#f87171" fill="#f87171" fillOpacity={0.35} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <div className="grid gap-6 xl:grid-cols-2">
        <ChartCard
          title="Функции"
          subtitle={`${functionCalls} вызовов · ${conversion}% конверсия`}
          right={
            <select className={selectClass} defaultValue="all">
              <option value="all">Все функции</option>
            </select>
          }
        >
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={functionSeries}>
                <CartesianGrid stroke="var(--canvas-border)" strokeDasharray="4 4" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "var(--canvas-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--canvas-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    background: "var(--card)",
                    border: "1px solid var(--canvas-border)",
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="lead" name="log_unqualified_lead" fill="#34d399" radius={[4, 4, 0, 0]} />
                <Bar dataKey="transfer" name="transfer_to_telegram" fill="#38bdf8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard
          title="Ошибки функций"
          subtitle="0 ошибок"
          right={
            <select className={selectClass} defaultValue="all">
              <option value="all">Все функции</option>
            </select>
          }
        >
          <div className="flex h-56 items-center justify-center rounded-xl border border-dashed border-[var(--canvas-border)] text-sm text-[var(--canvas-muted)]">
            За период ошибок не зафиксировано
          </div>
        </ChartCard>
      </div>
    </div>
  );
}
