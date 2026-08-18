"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { useToast } from "@/hooks/useToast";
import {
  getCrmFunnel,
  getCrmPerformance,
  getPipelines,
  type CrmFunnelResponse,
  type CrmPerformanceResponse,
  type CrmPipeline,
} from "@/lib/crm/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

type PeriodKey = "today" | "week" | "month" | "all";

const PERIODS: Array<{ key: PeriodKey; label: string }> = [
  { key: "today", label: "Сегодня" },
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
  { key: "all", label: "Всё время" },
];

const CHART_COLORS = ["#8b5cf6", "#22d3ee", "#34d399", "#fbbf24", "#f472b6", "#60a5fa"];

function periodRange(period: PeriodKey): { start?: string; end?: string } {
  if (period === "all") return {};
  const end = new Date();
  const start = new Date(end);
  if (period === "today") {
    start.setHours(0, 0, 0, 0);
  } else if (period === "week") {
    start.setDate(start.getDate() - 7);
  } else {
    start.setMonth(start.getMonth() - 1);
  }
  return { start: start.toISOString(), end: end.toISOString() };
}

function num(value: string | number): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

export default function CrmAnalyticsPage() {
  const { showToast } = useToast();
  const [pipelines, setPipelines] = useState<CrmPipeline[]>([]);
  const [pipelineId, setPipelineId] = useState<string>("");
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [funnel, setFunnel] = useState<CrmFunnelResponse | null>(null);
  const [performance, setPerformance] = useState<CrmPerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const range = useMemo(() => periodRange(period), [period]);

  const loadPipelines = useCallback(async () => {
    const list = await getPipelines();
    setPipelines(list);
    const preferred =
      list.find((p) => p.is_default)?.id ?? list[0]?.id ?? "";
    setPipelineId((prev) => prev || preferred);
  }, []);

  const loadAnalytics = useCallback(async () => {
    if (!pipelineId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [funnelData, perfData] = await Promise.all([
        getCrmFunnel(pipelineId, range.start, range.end),
        getCrmPerformance(range.start, range.end),
      ]);
      setFunnel(funnelData);
      setPerformance(perfData);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить аналитику."), "error");
    } finally {
      setLoading(false);
    }
  }, [pipelineId, range.end, range.start, showToast]);

  useEffect(() => {
    void loadPipelines().catch((error) => {
      showToast(getApiErrorMessage(error, "Не удалось загрузить воронки."), "error");
      setLoading(false);
    });
  }, [loadPipelines, showToast]);

  useEffect(() => {
    void loadAnalytics();
  }, [loadAnalytics]);

  const funnelChartData = useMemo(() => {
    const stages = [...(funnel?.stages ?? [])].sort((a, b) => a.position - b.position);
    return stages.map((stage, index) => {
      const count = stage.deal_count;
      const prev = index === 0 ? count : stages[index - 1]?.deal_count || 0;
      const conversion = prev > 0 ? Math.round((count / prev) * 1000) / 10 : 0;
      return {
        name: stage.stage_name,
        deals: count,
        amount: num(stage.amount_sum),
        conversion,
      };
    });
  }, [funnel]);

  const performanceBars = useMemo(
    () =>
      (performance?.items ?? []).map((row, index) => ({
        name: row.assigned_user_id
          ? `Менеджер ${row.assigned_user_id.slice(0, 6)}`
          : "Без назначения",
        won: row.won_count,
        lost: row.lost_count,
        revenue: num(row.revenue),
        fill: CHART_COLORS[index % CHART_COLORS.length],
      })),
    [performance],
  );

  const revenuePie = useMemo(
    () =>
      performanceBars
        .filter((row) => row.revenue > 0)
        .map((row) => ({ name: row.name, value: row.revenue, fill: row.fill })),
    [performanceBars],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6">
      <header className="space-y-3">
        <CrmSubNav />
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300/80">
              CRM Analytics
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-zinc-50">Аналитика</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Воронка конверсии и эффективность менеджеров
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={pipelineId}
              onChange={(e) => setPipelineId(e.target.value)}
              className="rounded-xl border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
            >
              {pipelines.length === 0 ? (
                <option value="">Нет воронок</option>
              ) : (
                pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))
              )}
            </select>
            <div className="flex flex-wrap gap-1.5">
              {PERIODS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setPeriod(item.key)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-xs font-medium transition",
                    period === item.key
                      ? "border-violet-500/60 bg-violet-500/15 text-violet-100"
                      : "border-zinc-700 text-zinc-400 hover:text-zinc-200",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      {loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка аналитики…
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label="Сделок в периоде" value={String(funnel?.total_deals ?? 0)} />
            <StatCard label="Выиграно" value={String(funnel?.won_deals ?? 0)} />
            <StatCard
              label="Конверсия"
              value={`${Math.round((funnel?.conversion_rate ?? 0) * 1000) / 10}%`}
            />
          </div>

          <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-2">
            <section className="rounded-2xl border border-zinc-800/90 bg-zinc-950/50 p-4">
              <h2 className="text-sm font-semibold text-zinc-100">Воронка продаж</h2>
              <p className="mt-1 text-xs text-zinc-500">
                Количество сделок по этапам и конверсия между соседними этапами
              </p>
              <div className="mt-4 h-80 w-full">
                {funnelChartData.length === 0 ? (
                  <EmptyChart />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={funnelChartData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="name" tick={{ fill: "#a1a1aa", fontSize: 11 }} />
                      <YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{
                          background: "#09090b",
                          border: "1px solid #3f3f46",
                          borderRadius: 12,
                        }}
                      />
                      <Legend />
                      <Bar dataKey="deals" name="Сделки" fill="#8b5cf6" radius={[8, 8, 0, 0]} />
                      <Bar dataKey="conversion" name="Конверсия %" fill="#22d3ee" radius={[8, 8, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-800/90 bg-zinc-950/50 p-4">
              <h2 className="text-sm font-semibold text-zinc-100">Эффективность менеджеров</h2>
              <p className="mt-1 text-xs text-zinc-500">
                Закрытые сделки (won/lost) и выручка
              </p>
              <div className="mt-4 h-80 w-full">
                {performanceBars.length === 0 ? (
                  <EmptyChart />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={performanceBars} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="name" tick={{ fill: "#a1a1aa", fontSize: 11 }} />
                      <YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{
                          background: "#09090b",
                          border: "1px solid #3f3f46",
                          borderRadius: 12,
                        }}
                      />
                      <Legend />
                      <Bar dataKey="won" name="Won" fill="#34d399" radius={[8, 8, 0, 0]} />
                      <Bar dataKey="lost" name="Lost" fill="#fb7185" radius={[8, 8, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-800/90 bg-zinc-950/50 p-4 xl:col-span-2">
              <h2 className="text-sm font-semibold text-zinc-100">Выручка по менеджерам</h2>
              <div className="mt-4 h-72 w-full">
                {revenuePie.length === 0 ? (
                  <EmptyChart />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={revenuePie}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={110}
                        label
                      >
                        {revenuePie.map((entry) => (
                          <Cell key={entry.name} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          background: "#09090b",
                          border: "1px solid #3f3f46",
                          borderRadius: 12,
                        }}
                      />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-50">{value}</p>
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-zinc-800 text-sm text-zinc-500">
      Нет данных за выбранный период
    </div>
  );
}
