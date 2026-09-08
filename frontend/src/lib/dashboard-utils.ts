import type {
  DashboardDailyPoint,
  DashboardStatsResponse,
  DailyChartPoint,
} from "@/types/dashboard";

const DAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export const FALLBACK_DASHBOARD_STATS: DashboardStatsResponse = {
  total_unique_dialogs: 0,
  total_messages_dispatched: 0,
  api_token_expenditure: 0,
  active_agents: 0,
  inactive_agents: 0,
  subscription_balance: 0,
  subscription_plan: "FREE",
  agents: [],
  period_label: "last_7_days",
  daily_series: [],
};

/** Empty last-7-days skeleton (calendar order, UTC-aligned labels). */
export function emptyDailyChartSeries(days = 7): DailyChartPoint[] {
  const points: DailyChartPoint[] = [];
  const today = new Date();
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    d.setUTCDate(d.getUTCDate() - offset);
    points.push({
      date: d.toISOString().slice(0, 10),
      label: DAY_LABELS[(d.getUTCDay() + 6) % 7] ?? "Пн",
      messages: 0,
      dialogs: 0,
    });
  }
  return points;
}

/**
 * Prefer real `daily_series` from the API. Never invent weekday weights from
 * lifetime totals — that caused the "messages on every day" chart bug.
 */
export function buildDailyChartSeries(stats: DashboardStatsResponse): DailyChartPoint[] {
  const series = stats.daily_series;
  if (Array.isArray(series) && series.length > 0) {
    return series.map((point: DashboardDailyPoint) => ({
      date: point.date,
      label: point.label,
      messages: Math.max(0, Number(point.messages) || 0),
      dialogs: Math.max(0, Number(point.dialogs) || 0),
    }));
  }
  return emptyDailyChartSeries();
}

export function buildFallbackChartSeries(): DailyChartPoint[] {
  return emptyDailyChartSeries();
}

export function countActiveLeads(stats: DashboardStatsResponse): number {
  if (stats.agents.length > 0) {
    return stats.agents.reduce((sum, agent) => sum + agent.unique_dialogs, 0);
  }
  return stats.active_agents * 12 + stats.total_unique_dialogs;
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}
